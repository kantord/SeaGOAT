import os
import tempfile
from pathlib import Path

import orjson


def get_json_file_contents(file_path: Path):
    with open(str(file_path), "rb") as file:
        file_content = file.read()
        if not file_content:
            return None

        return orjson.loads(file_content)


def write_to_json_file(file_path: Path, data) -> None:
    # Write through a temporary file and os.replace so a concurrent reader
    # never sees a half-written file.
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=file_path.parent, prefix=f".{file_path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(orjson.dumps(data))
        os.replace(temp_path, file_path)
    finally:
        Path(temp_path).unlink(missing_ok=True)
