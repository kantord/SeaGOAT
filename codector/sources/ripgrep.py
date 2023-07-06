from pathlib import Path
from ripgrepy import Ripgrepy
from codector.repository import Repository
from codector.common import SUPPORTED_FILE_TYPES


def _fetch(query_text: str, path: str):
    results = []
    for result in Ripgrepy(query_text, path).json().run().as_dict:
        result_data = result["data"]
        absolute_path = result_data["path"]["text"]
        relative_path = Path(absolute_path).relative_to(path)
        line_number = int(result_data["line_number"])

        if relative_path.suffix not in SUPPORTED_FILE_TYPES:
            continue

        results.append(
            {
                "absolute_path": absolute_path,
                "relative_path": relative_path,
                "line_number": line_number,
            }
        )

    return results


def initialize(repository: Repository):
    path = repository.path

    def fetch(query_text: str):
        return _fetch(query_text, path)

    return fetch
