# pylint: disable=too-few-public-methods
from dataclasses import dataclass
from pathlib import Path
from typing import Set


@dataclass(frozen=True)
class ResultLine:
    line: int
    vector_distance: float


class Result:
    def __init__(self, path: str, full_path: Path) -> None:
        self.path: str = path
        self.full_path: Path = full_path
        self._lines: Set[ResultLine] = set()
        self.line_texts = self._read_lines()

    def _read_lines(self):
        with open(self.full_path, encoding="utf-8") as source_code_file:
            return source_code_file.read().splitlines()

    def add_line(self, line: int, vector_distance: float) -> None:
        self._lines.add(ResultLine(line, vector_distance))

    def get_lines(self):
        best_score = min(
            self._lines, key=lambda item: item.vector_distance
        ).vector_distance

        return [
            result_line.line
            for result_line in self._lines
            if result_line.vector_distance <= best_score * 1.2
        ]
