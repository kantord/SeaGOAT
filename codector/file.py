import time


class File:
    def __init__(self, path: str):
        self.path = path
        self._commit_times = set()
        self.commit_messages = sorted([])

    def __repr__(self):
        return f"<File {self.path} {self.get_score()}>"

    def get_score(self):
        current_time = int(time.time())

        return sum(
            1000 / max(int((current_time - committed_date) / 86400) ** 2, 1)
            for committed_date in self._commit_times
        )

    def _add_commit_message(self, message: str):
        self.commit_messages = sorted(
            set(self.commit_messages)
            | {
                message,
            }
        )

    def add_commit(self, commit):
        self._commit_times.add(commit.committed_date)
        self._add_commit_message(commit.message)

    def get_metadata(self):
        commit_messages = "\n".join(self.commit_messages)
        return f"""###
{commit_messages}"""
