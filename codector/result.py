# pylint: disable=too-few-public-methods
class Result:
    def __init__(self, path: str) -> None:
        self.path = path
        self.lines = set()

    def add_line(self, line: int) -> None:
        self.lines.add(line)
