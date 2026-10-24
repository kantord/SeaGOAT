import sys
import unicodedata

import pytest

from seagoat import _native
from tests.reference_chunking import get_chunks as reference_get_chunks

METADATA = "###\n    Filename: a.py\n    Commits:\nfix: something"

TRICKY_FILES = [
    [],
    [""],
    ["abc"],
    ["abcd"],
    ["a b c d", "", "}", "x"],
    ["    return x", "}", "", "", "", "", "", "", "def foo(bar):", "    pass"],
    # longer than 100 characters, multi-byte: truncation counts code points
    ["á" * 150, "😀" * 120 + "abcd", "中文字符" * 40],
    # combining marks and other characters where Rust's is_alphanumeric()
    # and Python's str.isalnum() disagree
    ["ःःःः", "कःाी", "áb́ć"],
    ["Ⅳ ½ ² ٣", "x" * 4],
    ["\t\x0b\x0c\r", "line with trailing spaces    "],
    [f"line {number}" for number in range(40)],
]


@pytest.mark.parametrize("lines", TRICKY_FILES)
def test_matches_python_reference(lines):
    expected = reference_get_chunks("a.py", "0123abc", lines, METADATA)

    assert _native.get_chunks("a.py", "0123abc", lines, METADATA) == expected


@pytest.mark.skipif(
    unicodedata.unidata_version != _native.UNICODE_VERSION,
    reason="isalnum table was generated for a different Unicode version",
)
def test_is_alnum_matches_python_for_every_code_point():
    mismatches = [
        hex(code_point)
        for code_point in range(sys.maxunicode + 1)
        if not 0xD800 <= code_point <= 0xDFFF
        and _native.is_alnum(chr(code_point)) != chr(code_point).isalnum()
    ]

    assert mismatches == []
