import os
import tempfile

import pytest
from chardet.universaldetector import UniversalDetector

from seagoat.utils.file_reader import read_file_with_correct_encoding

MISDETECTED_UTF8_EXAMPLES = [
    # (sequence, detected_encoding),  # detection_confidence
    (b"\xcc\x8fa\\>N7:A", "Windows-1252"),  # 0.73
    (b"\xdd\x81nl", "Windows-1254"),  # 0.7729647837244535
    (b"\xd8\x90Mas", "Windows-1254"),  # 0.6183718269795628
    (b"t\xd1\x8fXbci\x15\x1bE", "Windows-1254"),  # 0.322068659885189
    (b"\xde\x9cL&\x1ba\xca\xb4r1", "TIS-620"),  # 0.30841818174528296
    (
        b"qdl\t=\xdc\xb4\x10\x0e9\xe9\x9f\x9d\x03",
        "Windows-1254",
    ),  # 0.38648239186222677
    (b"#L)Xlg<\xd6\x90x", "Windows-1254"),  # 0.7729647837244535
    (b"$\xc6\x8f>.", "Windows-1252"),  # 0.73
    (b"\xdf\x8fO\x15mg$G", "Windows-1254"),  # 0.6870798077550698
    (b"da\xd4\x9e|", "Windows-1254"),  # 0.5153098558163024
    (b"\xc7\x8fN.f\x1dgmk`", "Windows-1254"),  # 0.8833883242565184
    (b"\x02\xc4\xa0\xd4\xba%/", "TIS-620"),  # 0.8095977270813678
    (b"K\x1f<\xec\x90\xb8", "Windows-1252"),  # 0.73
    (b"@<L\xd2\x90 ", "Windows-1252"),  # 0.73
    (b"U \x19\x04\x19\x04\x7f<Iu\xd9\x8dx\x1e", "Windows-1252"),  # 0.73
    (b"C\x0eju=\xd3\x8em\x15", "Windows-1254"),  # 0.6870798077550698
    (b"uu\x15\xd0\x90\x7fA", "Windows-1254"),  # 0.6183718269795628
    (b"\xc5\x8d!x>\t", "Windows-1252"),  # 0.73
    (b"\xd3\x9d>t", "Windows-1252"),  # 0.73
    (b"\xc5\x8dTa5", "Windows-1254"),  # 0.5153098558163024
]


@pytest.mark.parametrize("sequence, detected_encoding", MISDETECTED_UTF8_EXAMPLES)
def test_file_reader_does_not_crash_because_of_misdetected_utf8(
    sequence: bytes, detected_encoding: str
):
    # the fallback encoding is utf8 as that is what most projects are expected to use

    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(sequence)

    try:
        # Ensure chardet detects the expected encoding
        # If it does not detect as that encoding, the test case might be useless
        test_detector = UniversalDetector()
        with open(temp_file.name, "rb") as file:
            for line in file:
                test_detector.feed(line)
                if test_detector.done:
                    break
        test_detector.close()
        detected = test_detector.result["encoding"]
        assert detected == detected_encoding

        # Now, proceed with the read_file_with_correct_encoding
        content = read_file_with_correct_encoding(temp_file.name)
        assert content is not None
    finally:
        os.unlink(temp_file.name)
