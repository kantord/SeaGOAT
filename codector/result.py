# pylint: disable=too-few-public-methods
from pathlib import Path


class Result:
    def __init__(self, path: str, full_path: Path) -> None:
        self.path = path
        self.full_path = full_path
        self._lines = set()
        self.line_texts = self._read_lines()

    def _read_lines(self):
        with open(self.full_path, encoding="utf-8") as source_code_file:
            return source_code_file.read().splitlines()

    def add_line(self, line: int, vector_distance: float) -> None:
        self._lines.add((line, vector_distance))

    def get_lines(self):
        best_score = min(self._lines, key=lambda x: x[1])[1]

        return [line for line, score in self._lines if score <= best_score * 1.2]
