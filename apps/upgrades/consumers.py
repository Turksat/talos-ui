import json
from channels.generic.websocket import AsyncWebsocketConsumer


class UpgradeProgressConsumer(AsyncWebsocketConsumer):
    """Subscribe to upgrade job progress events via Redis channel layer."""

    async def connect(self):
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.group_name = f'upgrade_{self.job_id}'

        if not self.scope['user'].is_authenticated:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        pass  # Client does not send messages to this consumer

    async def upgrade_progress(self, event):
        """Receive upgrade.progress message from channel layer and forward to WebSocket."""
        await self.send(json.dumps({
            'type': 'progress',
            'node': event.get('node', ''),
            'status': event.get('status', ''),
            'message': event.get('message', ''),
            'done': event.get('done', False),
        }))
