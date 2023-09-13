# pylint: disable=too-few-public-methods
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict
from typing import List
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

    def to_json(self, query: str):
        return {
            "score": round(self.get_score(query), 4),
            "line": self.line,
            "lineText": self.line_text,
            "resultTypes": list(sorted(set(str(t) for t in self.types))),
        }


@dataclass(frozen=True)
class ResultBlock:
    lines: List[ResultLine]

    def _get_line_count_per_type(self) -> Dict[str, int]:
        counts = Counter()

        for line in self.lines:
            for type_ in line.types:
                counts[str(type_)] += 1

        return dict(counts)

    def to_json(self, query: str):
        return {
            "lines": [line.to_json(query) for line in self.lines],
            "lineTypeCount": self._get_line_count_per_type(),
        }


class Result:
    def __init__(self, path: str, full_path: Path) -> None:
        self.path: str = path
        self.full_path: Path = full_path
        self.lines: Dict[int, ResultLine] = {}
        self.line_texts = self._read_lines()

    def __repr__(self) -> str:
        return f"Result(path={self.path})"

    def extend(self, other) -> None:
        self.lines.update(other.lines)

    def _read_lines(self):
        with open(self.full_path, encoding="utf-8") as source_code_file:
            return source_code_file.read().splitlines()

    def add_line(self, line: int, vector_distance: float) -> None:
        types = set()
        if line in self.lines and self.lines[line].vector_distance < vector_distance:
            vector_distance = self.lines[line].vector_distance
            types = self.lines[line].types

        types.add(
            ResultLineType.RESULT,
        )

        self.lines[line] = ResultLine(
            line,
            vector_distance,
            self.line_texts[line - 1],
            types,
        )

    def get_best_score(self, query: str) -> float:
        return min(
            (x for x in self.lines.values() if ResultLineType.RESULT in x.types),
            key=lambda item: item.get_score(query),
        ).get_score(query)

    def get_lines(self, query: str):
        best_score = self.get_best_score(query)

        return list(
            sorted(
                set(
                    result_line.line
                    for result_line in self.lines.values()
                    if (result_line.get_score(query) <= best_score * 10)
                    or ResultLineType.CONTEXT in result_line.types
                )
            )
        )

    def get_result_blocks(self, query):
        lines_to_include = [
            line
            for line in sorted(self.lines.values(), key=lambda item: item.line)
            if line.line in self.get_lines(query)
        ]
        blocks = []

        for line in lines_to_include:
            distance_from_previous_line = (
                line.line - blocks[-1].lines[-1].line if blocks else 0
            )

            if not blocks or distance_from_previous_line > 1:
                blocks.append(ResultBlock(lines=[]))

            blocks[-1].lines.append(line)

        return blocks

    def to_json(self, query: str):
        return {
            "path": self.path,
            "fullPath": str(self.full_path),
            "score": round(self.get_best_score(query), 4),
            "blocks": [block.to_json(query) for block in self.get_result_blocks(query)],
        }

    def add_context_lines(self, lines: int):
        if lines == 0:
            return

        direction = lines // abs(lines)
        for result_line, _ in list(self.lines.items()):
            for offset in range(abs(lines)):
                new_line = result_line + (offset + 1) * direction

                if (new_line) not in range(len(self.line_texts)):
                    continue

                if new_line not in self.lines:
                    self.lines[new_line] = ResultLine(
                        line=new_line,
                        vector_distance=0.0,
                        line_text=self.line_texts[new_line - 1],
                        types={ResultLineType.CONTEXT},
                    )

                self.lines[new_line].add_type(ResultLineType.CONTEXT)
