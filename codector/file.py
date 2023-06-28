import time
import hashlib
from typing import List

from chromadb.errors import Dict


class File:
    def __init__(self, path: str, absolute_path: str):
        self.path = path
        self.absolute_path = absolute_path
        self._commit_times = set()
        self.commit_messages = set()

    def __repr__(self):
        return f"<File {self.path} {self.get_score()}>"

    def get_score(self):
        current_time = int(time.time())

        return sum(
            1000 / max(int((current_time - committed_date) / 86400) ** 2, 1)
            for committed_date in self._commit_times
        )

    def _add_commit_message(self, message: str):
        self.commit_messages.add(message)

    def add_commit(self, commit):
        self._commit_times.add(commit.committed_date)
        self._add_commit_message(commit.message)

    def get_metadata(self):
        commit_messages = "\n-".join(sorted(self.commit_messages))
        return f"""
    ###
    Filename: {self.path}
    Commits:
{commit_messages}"""

    def _get_file_lines(self) -> Dict[int, str]:
        with open(self.absolute_path, "r", encoding="utf-8") as source_code_file:
            lines = {
                (i + 1): line
                for i, line in enumerate(source_code_file.read().splitlines())
            }

        return lines

    def _format_chunk_summary(self, relevant_lines: List[str]):
        truncated_lines = [line[:100] for line in relevant_lines]
        chunk = "\n".join(truncated_lines)
        chunk = chunk + self.get_metadata()

        return chunk

    def _get_chunk_for_line(self, line_number: int, lines: Dict[int, str]):
        previous_line = (
            [lines[line_number - 1]] if line_number - 1 in lines.keys() else []
        )
        next_line = [lines[line_number + 1]] if line_number + 1 in lines.keys() else []
        relevant_lines = previous_line + [lines[line_number]] + next_line
        return FileChunk(self, line_number, self._format_chunk_summary(relevant_lines))

    def get_chunks(self):
        try:
            lines = self._get_file_lines()
            return [
                self._get_chunk_for_line(line_number, lines)
                for line_number in lines.keys()
            ]

        except FileNotFoundError:
            return []


# pylint: disable=too-few-public-methods
class FileChunk:
    def __init__(self, parent: File, codeline: int, chunk: str):
        self.path = parent.path
        self.codeline = codeline
        self.chunk = chunk
        self.chunk_id = self._get_id()

    def _get_id(self):
        text = f"""
        Path: {self.path}
        Code line: {self.codeline}
        Chunk: {self.chunk}
        """
        return hashlib.sha256(text.encode()).hexdigest()
