from seagoat.repository import Repository

from seagoat.result import Result, ResultLine, ResultLineType
import pytest


@pytest.fixture
def fakefile(repo):
    def create_file(filename: str, contents: str):
        repo.add_file_change_commit(
            filename,
            contents,
            author=repo.actors["John Doe"],
            commit_message="add my fake file",
        )
        repository = Repository(repo.working_dir)
        repository.analyze_files()
        return repository.get_file(filename)

    return create_file


def test_to_result_line_correct_output_example1(fakefile):
    fake_result = Result("", fakefile("file1.txt", ""))
    line = ResultLine(fake_result, 1, 0.5, "some line text", {ResultLineType.RESULT})
    result_dict = line.to_json()
    assert result_dict == {
        "score": 0.25,
        "line": 1,
        "lineText": "some line text",
        "resultTypes": ["result"],
    }


def test_to_result_line_correct_output_example2(fakefile):
    fake_result = Result("", fakefile("file1.txt", "another line of text"))
    line = ResultLine(
        fake_result, 2, 0.2, "another line of text", {ResultLineType.RESULT}
    )
    result_dict = line.to_json()
    assert result_dict == {
        "score": 0.1,
        "line": 2,
        "lineText": "another line of text",
        "resultTypes": ["result"],
    }


def test_to_result_json_correct_output_example1(fakefile):
    my_file = fakefile("example1.txt", "Line 1\nLine 2\nLine 3\n")
    result = Result("", my_file)
    result.add_line(1, 0.5)
    result.add_line(2, 0.3)

    result_dict = result.to_json()
    assert result_dict == {
        "score": 0.225,
        "path": "example1.txt",
        "fullPath": my_file.absolute_path,
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


def test_to_result_json_correct_output_example2(fakefile):
    contents = "\n".join(f"This is line {i + 1}" for i in range(10))
    my_file = fakefile("example2.txt", contents)
    result = Result("", my_file)
    result.add_line(1, 0.5)
    result.add_line(5, 0.1)

    result_dict = result.to_json()
    assert result_dict == {
        "score": 0.075,
        "path": "example2.txt",
        "fullPath": my_file.absolute_path,
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
