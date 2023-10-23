import os
import tempfile
from pathlib import Path

from seagoat.result import Result
from seagoat.result import ResultLine
from seagoat.result import ResultLineType


def test_to_result_line_correct_output_example1():
    line = ResultLine(1, 0.5, "some line text", {ResultLineType.RESULT})
    result_dict = line.to_json("")
    assert result_dict == {
        "score": 0.25,
        "line": 1,
        "lineText": "some line text",
        "resultTypes": ["result"],
    }


def test_to_result_line_correct_output_example2():
    line = ResultLine(2, 0.2, "another line of text", {ResultLineType.RESULT})
    result_dict = line.to_json("")
    assert result_dict == {
        "score": 0.1,
        "line": 2,
        "lineText": "another line of text",
        "resultTypes": ["result"],
    }


def test_to_result_json_correct_output_example1():
    with tempfile.TemporaryDirectory() as tmpdirname:
        file_path = os.path.join(tmpdirname, "example1.txt")
        with open(file_path, "w", encoding="utf-8") as tmp_file:
            tmp_file.write("Line 1\nLine 2\nLine 3\n")

        result = Result("example1.txt", Path(file_path))
        result.add_line(1, 0.5)
        result.add_line(2, 0.3)

        result_dict = result.to_json("")
        assert result_dict == {
            "score": 0.225,
            "path": "example1.txt",
            "fullPath": file_path,
            "blocks": [
                {
                    "score": 0.15,
                    "lineTypeCount": {"result": 2},
                    "lines": [
                        {
                            "score": 0.25,
                            "line": 1,
                            "lineText": "Line 1",
                            "resultTypes": ["result"],
                        },
                        {
                            "score": 0.15,
                            "line": 2,
                            "lineText": "Line 2",
                            "resultTypes": ["result"],
                        },
                    ],
                },
            ],
        }


def test_to_result_json_correct_output_example2():
    with tempfile.TemporaryDirectory() as tmpdirname:
        file_path = os.path.join(tmpdirname, "example2.txt")
        with open(file_path, "w", encoding="utf-8") as tmp_file:
            tmp_file.write("\n".join(f"This is line {i + 1}" for i in range(10)))

        result = Result("example2.txt", Path(file_path))
        result.add_line(1, 0.5)
        result.add_line(5, 0.1)

        result_dict = result.to_json("")
        assert result_dict == {
            "score": 0.075,
            "path": "example2.txt",
            "fullPath": file_path,
            "blocks": [
                {
                    "score": 0.25,
                    "lineTypeCount": {"result": 1},
                    "lines": [
                        {
                            "score": 0.25,
                            "line": 1,
                            "lineText": "This is line 1",
                            "resultTypes": ["result"],
                        },
                    ],
                },
                {
                    "score": 0.05,
                    "lineTypeCount": {"result": 1},
                    "lines": [
                        {
                            "score": 0.05,
                            "line": 5,
                            "lineText": "This is line 5",
                            "resultTypes": ["result"],
                        },
                    ],
                },
            ],
        }
