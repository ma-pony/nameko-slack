import asyncio
import re
from functools import partial

import eventlet
from nameko.exceptions import ConfigurationError
from nameko.extensions import Entrypoint, ProviderCollector, SharedExtension
from slack import RTMClient

from nameko_slackclient import constants

EVENT_TYPE_MESSAGE = "message"


class SlackRTMClientManager(SharedExtension, ProviderCollector):
    def __init__(self):

        super(SlackRTMClientManager, self).__init__()

        self.read_interval = 1

        self.clients = {}

    def setup(self):

        try:
            config = self.container.config[constants.CONFIG_KEY]
        except KeyError:
            raise ConfigurationError(
                "`{}` config key not found".format(constants.CONFIG_KEY)
            )
        asyncio.set_event_loop(asyncio.new_event_loop())

        token = config.get("TOKEN")
        clients = config.get("BOTS")
        if token:
            self.clients[constants.DEFAULT_BOT_NAME] = RTMClient(token=token)
        if clients:
            for bot_name, token in clients.items():
                self.clients[bot_name] = RTMClient(token=token)

        if not self.clients:
            raise ConfigurationError(
                "At least one token must be provided in `{}` config".format(
                    constants.CONFIG_KEY
                )
            )

    def start(self):
        for bot_name, client in self.clients.items():
            run = partial(self.run, client)
            self.container.spawn_managed_thread(run)

    def run(self, client):
        while True:
            client.start()
            eventlet.sleep(self.read_interval)

    def stop(self):
        for bot_name, client in self.clients.items():
            if client:
                client.stop()


class RTMEventHandlerEntrypoint(Entrypoint):

    clients = SlackRTMClientManager()

    def __init__(self, event_type=None, bot_name=None, **kwargs):
        self.bot_name = bot_name or constants.DEFAULT_BOT_NAME
        self.event_type = event_type
        super(RTMEventHandlerEntrypoint, self).__init__(**kwargs)

    def setup(self):
        self.clients.register_provider(self)

    def stop(self):
        self.clients.unregister_provider(self)

    def handle_event(self, event):
        if self.event_type and event.get("type") != self.event_type:
            return
        args = (event,)
        kwargs = {}
        context_data = {}
        self.container.spawn_worker(self, args, kwargs, context_data=context_data)


handle_event = RTMEventHandlerEntrypoint.decorator


class RTMMessageHandlerEntrypoint(RTMEventHandlerEntrypoint):
    def __init__(self, message_pattern=None, **kwargs):
        if message_pattern:
            self.message_pattern = re.compile(message_pattern)
        else:
            self.message_pattern = None
        super(Entrypoint, self).__init__(**kwargs)

    def setup(self):
        self.clients.register_provider(self)
        RTMClient.on(event=EVENT_TYPE_MESSAGE, callback=self.handle_message)

    def stop(self):
        self.clients.unregister_provider(self)

    def handle_message(self, **payload):

        data = payload["data"]
        web_client = payload["web_client"]
        if self.message_pattern:
            match = self.message_pattern.match(data.get("text", ""))
            if match:
                kwargs = match.groupdict()
                args = () if kwargs else match.groups()
                args = (data, data.get("text")) + args
            else:
                return
        else:
            args = (data, data.get("text"))
            kwargs = {}
        context_data = {}
        handle_result = partial(self.handle_result, web_client, data)
        self.container.spawn_worker(
            self, args, kwargs, context_data=context_data, handle_result=handle_result
        )

    def handle_result(self, web_client, data, worker_ctx, result, exc_info):
        if result:
            web_client.chat_postMessage(
                channel=data["channel"], thread_ts=data["ts"], text=result
            )
        return result, exc_info


handle_message = RTMMessageHandlerEntrypoint.decorator
