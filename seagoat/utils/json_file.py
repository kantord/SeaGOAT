from pathlib import Path

import orjson


def get_json_file_contents(file_path: Path):
    with open(str(file_path), "rb") as file:
        return orjson.loads(file.read())


def write_to_json_file(file_path: Path, data: dict) -> None:
    with open(str(file_path), "wb") as file:
        file.write(orjson.dumps(data))
