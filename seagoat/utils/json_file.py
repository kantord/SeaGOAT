import orjson


def get_json_file_contents(file_path: str):
    with open(file_path, "r", encoding="utf-8") as file:
        return orjson.loads(file.read())
