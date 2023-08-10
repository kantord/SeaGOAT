# pylint: disable=too-few-public-methods
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict
from typing import Set


class ResultLineType(Enum):
    RESULT = "result"
    CONTEXT = "context"

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class ResultLine:
    line: int
    vector_distance: float
    line_text: str
    types: Set[ResultLineType]

    def _get_number_of_exact_matches(self, query: str) -> int:
        terms = re.split(r"\s+", query)
        pattern = ".*".join(map(re.escape, terms))

        if re.search(pattern, self.line_text, re.IGNORECASE):
            return 1
        return 0

    def get_score(self, query: str) -> float:
        return self.vector_distance / (1 + self._get_number_of_exact_matches(query))

    def add_type(self, type_: ResultLineType) -> None:
        self.types.add(type_)

    def to_json(self):
        return {
            "line": self.line,
            "lineText": self.line_text,
            "resultTypes": list(sorted(set(str(t) for t in self.types))),
        }


class Result:
    def __init__(self, path: str, full_path: Path) -> None:
        self.path: str = path
        self.full_path: Path = full_path
        self.lines: Dict[int, ResultLine] = {}
        self.line_texts = self._read_lines()

    def extend(self, other) -> None:
        self.lines.update(other.lines)

    def _read_lines(self):
        with open(self.full_path, encoding="utf-8") as source_code_file:
            return source_code_file.read().splitlines()

    def add_line(self, line: int, vector_distance: float) -> None:
        if line in self.lines:
            raise RuntimeError(f"Line {line} already exists in result {self.path}")
        self.lines[line] = ResultLine(
            line,
            vector_distance,
            self.line_texts[line - 1],
            {
                ResultLineType.RESULT,
            },
        )

    def get_best_score(self, query: str) -> float:
        return min(
            self.lines.values(), key=lambda item: item.get_score(query)
        ).get_score(query)

    def get_lines(self, query: str):
        best_score = self.get_best_score(query)

        return list(
            sorted(
                set(
                    result_line.line
                    for result_line in self.lines.values()
                    if result_line.get_score(query) <= best_score * 1.2
                )
            )
        )

    def to_json(self):
        return {
            "path": self.path,
            "fullPath": str(self.full_path),
            "lines": [
                line.to_json()
                for line in sorted(self.lines.values(), key=lambda item: item.line)
            ],
        }
