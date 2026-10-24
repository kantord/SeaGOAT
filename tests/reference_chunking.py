"""
The Python chunking that seagoat/gitfile.py used before it moved to Rust
(src/chunks.rs), kept unchanged as the reference the Rust port must match.
"""

import hashlib
from typing import Literal


def _line_has_relevant_data(line: str):
    alphanumeric_characters_count = 0
    for character in line:
        if character.isalnum():
            alphanumeric_characters_count += 1
        if alphanumeric_characters_count > 3:
            return True
    return False


def _get_context_lines(
    lines: dict[int, str], line_number: int, direction: Literal[-1, 1]
) -> list[str]:
    context_lines = []
    for i in range(1, 6):
        current_line_number = line_number + (direction * i)
        current_line = lines.get(current_line_number)

        if current_line is None:
            break

        if direction == -1:
            context_lines = [current_line] + context_lines
        else:
            context_lines.append(current_line)

        if _line_has_relevant_data(current_line):
            break

    return context_lines


def _get_id(path, object_id, codeline, chunk):
    text = f"""
        Path: {path}
        Object ID: {object_id}
        Code line: {codeline}
        Chunk: {chunk}
        """
    return hashlib.sha256(text.encode()).hexdigest()


def get_chunks(path, object_id, line_list: list[str], metadata: str):
    lines = {(i + 1): line for i, line in enumerate(line_list)}
    chunks = []
    for line_number, line in lines.items():
        if not _line_has_relevant_data(line):
            continue
        relevant_lines = (
            _get_context_lines(lines, line_number, -1)
            + [line]
            + _get_context_lines(lines, line_number, 1)
        )
        chunk = "\n".join(line[:100] for line in relevant_lines) + metadata
        chunks.append(
            (line_number, chunk, _get_id(path, object_id, line_number, chunk))
        )
    return chunks
