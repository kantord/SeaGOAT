import functools
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Set
from seagoat.gitfile import GitFile

from seagoat.utils.file_types import get_file_penalty_factor

SPLITTER_PATTERN = re.compile(r"\s+")


@functools.lru_cache(maxsize=100)
def compile_regex_pattern(query: str):
    terms = re.split(SPLITTER_PATTERN, query)
    pattern = ".*".join(map(re.escape, terms))

    return re.compile(pattern, re.IGNORECASE)


@functools.lru_cache(maxsize=10_000)
def get_number_of_exact_matches(line: str, query: str):
    pattern = compile_regex_pattern(query)

    if re.search(pattern, line):
        return 1
    return 0


def get_best_score(result) -> float:
    best_score = min(
        (x for x in result.lines.values() if ResultLineType.RESULT in x.types),
        key=lambda item: item.get_score(),
    ).get_score()

    best_score *= get_file_penalty_factor(result.gitfile.absolute_path)

    return best_score


class ResultLineType(Enum):
    RESULT = "result"
    CONTEXT = "context"
    BRIDGE = "bridge"

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class ResultLine:
    parent: "Result"
    line: int
    vector_distance: float
    line_text: str
    types: Set[ResultLineType]

    def get_score(self) -> float:
        return self.vector_distance / (
            1 + get_number_of_exact_matches(self.line_text, self.parent.query_text)
        )

    def add_type(self, type_: ResultLineType) -> None:
        self.types.add(type_)

    def to_json(self):
        return {
            "score": round(self.get_score(), 4),
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

    def _get_score(self) -> float:
        return min(
            line.get_score()
            for line in self.lines
            if ResultLineType.RESULT in line.types
        )

    def to_json(self):
        return {
            "score": self._get_score(),
            "lines": [line.to_json() for line in self.lines],
            "lineTypeCount": self._get_line_count_per_type(),
        }


class Result:
    def __init__(self, query_text: str, gitfile: GitFile) -> None:
        self.gitfile: GitFile = gitfile
        self.query_text: str = query_text
        self.lines: Dict[int, ResultLine] = {}

    def __repr__(self) -> str:
        return f"Result(path={self.gitfile.path})"

    def extend(self, other) -> None:
        self.lines.update(other.lines)

    def add_line(self, line: int, vector_distance: float) -> None:
        types = set()
        if line in self.lines and self.lines[line].vector_distance < vector_distance:
            vector_distance = self.lines[line].vector_distance
            types = self.lines[line].types

        types.add(
            ResultLineType.RESULT,
        )

        self.lines[line] = ResultLine(
            self,
            line,
            vector_distance,
            self.gitfile.lines[line],
            types,
        )

    def get_lines(self):
        best_score = get_best_score(self)

        return list(
            sorted(
                set(
                    result_line.line
                    for result_line in self.lines.values()
                    if (result_line.get_score() <= best_score * 10)
                    or ResultLineType.CONTEXT in result_line.types
                )
            )
        )

    def _merge_almost_touching_blocks(self, blocks):
        if len(blocks) == 0:
            return []

        merged_blocks = [blocks[0]]

        for block in blocks[1:]:
            last_block = merged_blocks[-1]
            last_line_of_last_block = last_block.lines[-1].line
            line_range_from_last_block = range(
                last_line_of_last_block + 1, block.lines[0].line
            )

            if len(line_range_from_last_block) <= 2:
                for line in line_range_from_last_block:
                    bridge_line = ResultLine(
                        self,
                        line,
                        0.0,
                        self.gitfile.lines[line],
                        {ResultLineType.BRIDGE},
                    )
                    last_block.lines.append(bridge_line)

                for line in block.lines:
                    last_block.lines.append(line)
            else:
                merged_blocks.append(block)

        return merged_blocks

    def get_result_blocks(self):
        self_lines = self.get_lines()
        lines_to_include = [
            line
            for line in sorted(self.lines.values(), key=lambda item: item.line)
            if line.line in self_lines
        ]
        blocks = []

        for line in lines_to_include:
            distance_from_previous_line = (
                line.line - blocks[-1].lines[-1].line if blocks else 0
            )

            if not blocks or distance_from_previous_line > 1:
                blocks.append(ResultBlock(lines=[]))

            blocks[-1].lines.append(line)

        return self._merge_almost_touching_blocks(blocks)

    def to_json(self):
        return {
            "path": self.gitfile.path,
            "fullPath": str(self.gitfile.absolute_path),
            "score": round(get_best_score(self), 4),
            "blocks": [block.to_json() for block in self.get_result_blocks()],
        }

    def add_context_lines(self, lines: int):
        if lines == 0:
            return

        direction = lines // abs(lines)
        for result_line, _ in list(self.lines.items()):
            for offset in range(abs(lines)):
                new_line = result_line + (offset + 1) * direction

                if new_line not in self.gitfile.lines:
                    continue

                if new_line not in self.lines:
                    self.lines[new_line] = ResultLine(
                        self,
                        line=new_line,
                        vector_distance=0.0,
                        line_text=self.gitfile.lines[new_line],
                        types={ResultLineType.CONTEXT},
                    )

                self.lines[new_line].add_type(ResultLineType.CONTEXT)
