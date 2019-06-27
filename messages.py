import json

class MessageBuilder:
    messages = {}

    def __init__(self):
        self.reload()
    
    def reload(self):
        with open("messages.json", "r", encoding="utf-8") as file:
            self.messages = json.load(file)

    def build(self, msg_name, **kwargs):
        """Return the message of the given `msg_name` using
        the key word arguments to format it.
        """
        
        return self.messages[msg_name].format(**kwargs)

msg_builder = MessageBuilder()