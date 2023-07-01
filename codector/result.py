# pylint: disable=too-few-public-methods
from dataclasses import dataclass
from pathlib import Path
from typing import Set


@dataclass(frozen=True)
class ResultLine:
    line: int
    vector_distance: float
    line_text: str

    def _get_number_of_exact_matches(self, query: str) -> int:
        if query.lower() in self.line_text.lower():
            return 1
        return 0

    def get_score(self, query: str) -> float:
        return self.vector_distance - self._get_number_of_exact_matches(query)


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
        self._lines.add(ResultLine(line, vector_distance, self.line_texts[line - 1]))

    def get_lines(self, query: str):
        best_score = min(self._lines, key=lambda item: item.get_score(query)).get_score(
            query
        )

        return [
            result_line.line
            for result_line in self._lines
            if result_line.get_score(query) <= best_score * 1.2
        ]
