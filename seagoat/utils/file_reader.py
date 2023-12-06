from chardet.universaldetector import UniversalDetector


def read_file_as_binary(file_path: str):
    with open(file_path, "rb") as file:
        return file.read()


def autodecode_bytes(binary_data: bytes) -> str:
    detector = UniversalDetector()
    for line in binary_data.split(b"\n"):
        detector.feed(line)
        if detector.done:
            break
    detector.close()

    encoding = detector.result["encoding"] or "utf-8"

    if detector.result["confidence"] < 0.89:
        encoding = "utf-8"

    return binary_data.decode(encoding)


def read_file_with_correct_encoding(file_path: str) -> str:
    binary_data = read_file_as_binary(file_path)
    return autodecode_bytes(binary_data)
