class File:
    def __init__(self, path: str):
        self.path = path
        self.score = 0.0
        self.commit_messages = set()

    def increment_score(self, amount: float):
        self.score += amount

    def add_commit_message(self, message: str):
        self.commit_messages.add(message)
