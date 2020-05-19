import json

from utils import logger


class MessageBuilder:
    messages = {}

    def __init__(self):
        self.reload()

    def build(self, msg_name, **kwargs):
        """
        Build the message with name `msg_name` using the key word arguments to
        format it.
        """
        return self.messages[msg_name].format(**kwargs)

    def reload(self):
        """
        Reload messages definition from file.
        """
        logger.info("Reloading message configuration from file.")
        with open("config/messages.json", "r", encoding="utf-8") as file:
            self.messages = json.load(file)

    async def send(self, channel, msg_name, **kwargs):
        """
        Send the message with name `msg_name` in the given channel.
        """
        msg = self.build(msg_name, **kwargs)
        await channel.send(msg)


msg_builder = MessageBuilder()
