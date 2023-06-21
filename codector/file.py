import time


class File:
    def __init__(self, path: str):
        self.path = path
        self.score = 0.0
        self.commit_messages = []

    def _increment_score(self, committed_date):
        current_time = int(time.time())
        age_of_commit_in_seconds = current_time - committed_date
        age_of_commit_in_days = int(age_of_commit_in_seconds / 86400)
        self.score += 100 / (age_of_commit_in_days**2)

    def _add_commit_message(self, message: str):
        if message not in self.commit_messages:
            self.commit_messages.append(message)

    def add_commit(self, commit):
        self._add_commit_message(commit.message)
        self._increment_score(commit.committed_date)

    def get_metadata(self):
        commit_messages = "\n".join(self.commit_messages)
        return f"""###
{commit_messages}"""
