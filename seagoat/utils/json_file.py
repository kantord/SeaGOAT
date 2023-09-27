from pathlib import Path

import orjson


def get_json_file_contents(file_path: Path):
    with open(str(file_path), "rb") as file:
        file_content = file.read()
        if not file_content:
            return None

        return orjson.loads(file_content)


def write_to_json_file(file_path: Path, data: dict) -> None:
    with open(str(file_path), "wb") as file:
        file.write(orjson.dumps(data))
