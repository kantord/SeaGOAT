from pathlib import Path
from typing import Union

IGNORED_BRANCHES = {"gh-pages"}

TEXT_FILE_TYPES = {
    ".txt",
    ".md",
}

SUPPORTED_FILE_TYPES = TEXT_FILE_TYPES | {
    ".py",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".html",
    ".go",
    ".java",
    ".php",
    ".rb",
}


def is_file_type_supported(path: Union[Path, str]):
    return Path(path).suffix in SUPPORTED_FILE_TYPES


def get_file_penalty_factor(path: Union[Path, str]) -> float:
    # Text file lines are penalized compared to code file lines as they
    # generally have more meaningful words, but the user might be more likely
    # to be looking for code than text.
    if Path(path).suffix in TEXT_FILE_TYPES:
        return 1.5

    return 1.0
