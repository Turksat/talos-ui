import asyncio
import json
import subprocess
import threading
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


@database_sync_to_async
def get_cluster(cluster_id):
    from .models import Cluster
    return Cluster.objects.get(pk=cluster_id, is_active=True)


@database_sync_to_async
def get_cluster_node_ips(cluster_id):
    from .models import Node
    return list(Node.objects.filter(cluster_id=cluster_id).values_list('ip_address', flat=True))


class _SubprocessStream:
    """
    Runs a talosctl command in a background daemon thread.
    Puts (kind, data) tuples into an asyncio.Queue:
      ('line', str)   – one output line
      ('error', str)  – exception message
      ('done', None)  – stream ended
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self._loop = loop
        self._queue = queue
        self._proc: subprocess.Popen | None = None
        self._stopped = False

    def start(self, cluster, args: list, node_ip=None):
        def _worker():
            from .talosctl import TalosctlRunner
            try:
                with TalosctlRunner(cluster) as t:
                    cmd = t._base_cmd(node_ip) + args
                    self._proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    for line in self._proc.stdout:
                        if self._stopped:
                            break
                        asyncio.run_coroutine_threadsafe(
                            self._queue.put(('line', line.rstrip())), self._loop
                        )
                    self._proc.wait()
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(
                    self._queue.put(('error', str(exc))), self._loop
                )
            finally:
                asyncio.run_coroutine_threadsafe(
                    self._queue.put(('done', None)), self._loop
                )

        threading.Thread(target=_worker, daemon=True).start()

    def stop(self):
        self._stopped = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass


class ClusterEventsConsumer(AsyncWebsocketConsumer):
    """
    Stream events from all cluster nodes via:
      talosctl events --tail 20 -n <node1> -n <node2> ...
    """

    async def connect(self):
        if not self.scope['user'].is_authenticated:
            await self.close()
            return

        self.cluster_id = self.scope['url_route']['kwargs']['cluster_id']
        self._stream: _SubprocessStream | None = None
        self._drain_task: asyncio.Task | None = None
        await self.accept()

        try:
            cluster = await get_cluster(self.cluster_id)
        except Exception:
            await self.send(json.dumps({'type': 'error', 'line': 'Cluster not found'}))
            await self.close()
            return

        # Collect all known node IPs; fall back to endpoint IP if no nodes yet
        node_ips = await get_cluster_node_ips(self.cluster_id)
        if not node_ips:
            endpoint = cluster.endpoint.replace('https://', '').replace('http://', '')
            node_ips = [endpoint.split(':')[0]]

        self._queue: asyncio.Queue = asyncio.Queue()
        self._stream = _SubprocessStream(asyncio.get_running_loop(), self._queue)
        self._stream.start(
            cluster,
            ['events', '--tail', '20'],
            node_ip=node_ips,
        )
        self._drain_task = asyncio.create_task(self._drain())

    async def disconnect(self, code):
        if self._stream:
            self._stream.stop()
        if self._drain_task:
            self._drain_task.cancel()

    async def _drain(self):
        while True:
            kind, data = await self._queue.get()
            if kind == 'done':
                await self.send(json.dumps({'type': 'info', 'line': '[stream ended]'}))
                break
            elif kind == 'error':
                await self.send(json.dumps({'type': 'error', 'line': data}))
                break
            else:
                await self.send(json.dumps({'type': 'event', 'line': data}))


class NodeLogsConsumer(AsyncWebsocketConsumer):
    """
    Stream logs from a single node service via:
      talosctl logs --namespace system <service> --follow -n <node_ip>
    """

    async def connect(self):
        if not self.scope['user'].is_authenticated:
            await self.close()
            return

        self.cluster_id = self.scope['url_route']['kwargs']['cluster_id']
        self.node_ip = self.scope['url_route']['kwargs']['node_ip']
        self.service = self.scope['url_route']['kwargs'].get('service', 'kubelet')
        self._stream: _SubprocessStream | None = None
        self._drain_task: asyncio.Task | None = None
        await self.accept()

        try:
            cluster = await get_cluster(self.cluster_id)
        except Exception:
            await self.send(json.dumps({'type': 'error', 'line': 'Cluster not found'}))
            await self.close()
            return

        self._queue: asyncio.Queue = asyncio.Queue()
        self._stream = _SubprocessStream(asyncio.get_running_loop(), self._queue)
        self._stream.start(
            cluster,
            ['logs', self.service, '--follow'],
            node_ip=self.node_ip,
        )
        self._drain_task = asyncio.create_task(self._drain())

    async def disconnect(self, code):
        if self._stream:
            self._stream.stop()
        if self._drain_task:
            self._drain_task.cancel()

    async def _drain(self):
        while True:
            kind, data = await self._queue.get()
            if kind == 'done':
                await self.send(json.dumps({'type': 'info', 'line': '[stream ended]'}))
                break
            elif kind == 'error':
                await self.send(json.dumps({'type': 'error', 'line': data}))
                break
            else:
                await self.send(json.dumps({'type': 'log', 'line': data}))
