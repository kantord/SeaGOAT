from chardet import UniversalDetector


def read_file_as_binary(file_path: str):
    with open(file_path, "rb") as file:
        return file.read()


def autodecode_bytes(binary_data: bytes) -> str:
    # Nearly all files are UTF-8, and checking that is fast. Detecting the
    # encoding is slow, and it can mistake UTF-8 for another encoding
    try:
        return binary_data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    detector = UniversalDetector()
    for line in binary_data.split(b"\n"):
        detector.feed(line)
        if detector.done:
            break
    detector.close()

    encoding = detector.result["encoding"] or "utf-8"

    if detector.result["confidence"] < 0.89:
        encoding = "utf-8"

    # Files that are not valid in the detected encoding (for example a
    # Latin-1 file detected as UTF-8) are still searchable, with the invalid
    # bytes replaced
    return binary_data.decode(encoding, errors="replace")


def read_file_with_correct_encoding(file_path: str) -> str:
    binary_data = read_file_as_binary(file_path)
    return autodecode_bytes(binary_data)
