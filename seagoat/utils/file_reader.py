from chardet.universaldetector import UniversalDetector


def read_file_with_correct_encoding(file_path):
    try:
        # Try to read the file as UTF-8 first
        with open(file_path, encoding="utf-8") as file:
            return file.read()
    except UnicodeDecodeError:
        # If UTF-8 reading fails, then detect encoding and read accordingly
        detector = UniversalDetector()
        with open(file_path, "rb") as file:
            for line in file:
                detector.feed(line)
                if detector.done:
                    break
        detector.close()
        encoding = detector.result["encoding"] or "utf-8"

        with open(file_path, encoding=encoding) as file:
            return file.read()
