class File:
    def __init__(self, path: str):
        self.path = path
        self.score = 0.0
        self.commit_messages = []

    def increment_score(self, amount: float):
        self.score += amount

    def add_commit_message(self, message: str):
        if message not in self.commit_messages:
            self.commit_messages.append(message)

    def get_metadata(self):
        commit_messages = "\n".join(self.commit_messages)
        return f"""###
{commit_messages}"""
