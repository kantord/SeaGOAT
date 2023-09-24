from chardet.universaldetector import UniversalDetector


class FileReader:
    """A context manager to read a file with its detected encoding."""

    def __init__(self, file_path):
        self.file_path = file_path
        self.file = None

    def __enter__(self):
        detector = UniversalDetector()
        with open(self.file_path, "rb") as file:
            for line in file:
                detector.feed(line)
                if detector.done:
                    break
        detector.close()
        encoding = detector.result["encoding"] or "utf-8"
        self.file = open(self.file_path, "r", encoding=encoding)
        return self.file

    def __exit__(self, _, __, ___):
        if self.file:
            self.file.close()
