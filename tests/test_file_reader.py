import os
import tempfile

import pytest

from seagoat.utils.file_reader import read_file_with_correct_encoding

MISDETECTED_UTF8_EXAMPLES = [
    # (sequence, encoding chardet 5 detected),  # its detection confidence
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
def test_file_reader_reads_utf8_that_chardet_used_to_misdetect(
    sequence: bytes, detected_encoding: str
):
    # chardet 5 detected these UTF-8 sequences as detected_encoding. Valid
    # UTF-8 is now decoded as UTF-8 before encoding detection is consulted
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(sequence)

    try:
        content = read_file_with_correct_encoding(temp_file.name)
    finally:
        os.unlink(temp_file.name)

    assert content == sequence.decode("utf-8"), detected_encoding
