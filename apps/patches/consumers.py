import json
from channels.generic.websocket import AsyncWebsocketConsumer


class PatchProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.group_name = f'patch_{self.job_id}'

        if not self.scope['user'].is_authenticated:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        pass

    async def patch_progress(self, event):
        await self.send(json.dumps({
            'type': 'progress',
            'node': event.get('node', ''),
            'status': event.get('status', ''),
            'message': event.get('message', ''),
            'done': event.get('done', False),
        }))
