# pylint: disable=too-few-public-methods
from pathlib import Path


class Result:
    def __init__(self, path: str, full_path: Path) -> None:
        self.path = path
        self.full_path = full_path
        self.lines = set()
        self.line_texts = self._read_lines()

    def _read_lines(self):
        with open(self.full_path, encoding="utf-8") as source_code_file:
            return source_code_file.read().splitlines()

    def add_line(self, line: int) -> None:
        self.lines.add(line)
