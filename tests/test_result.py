from pathlib import Path
from seagoat.repository import Repository

from seagoat.result import Result
from tests.conftest import pytest


@pytest.fixture(name="create_result")
def create_result_(repo):
    def noop():
        pass

    def result_factory(query: str, fake_lines=None, lines_to_include=None):
        if lines_to_include is None:
            lines_to_include = [40]
        if fake_lines is None:
            fake_lines = {}
        test_file_path = "test.txt"
        fake_content = "".join(
            f"{fake_lines[i]}\n" if i in fake_lines else f"fake line {i}\n"
            for i in range(1, 100)
        )
        repo.add_file_change_commit(
            test_file_path,
            fake_content,
            author=repo.actors["John Doe"],
            commit_message="added my changes",
        )

        repository = Repository(repo.working_dir)
        repository.analyze_files()
        gitfile = repository.get_file("test.txt")
        result = Result(query, gitfile)
        for line in lines_to_include:
            result.add_line(line, 0.5)

        return result

    yield result_factory


def test_get_lines_without_context(create_result, repo):
    query = "famous typographic sample text"
    result = create_result(query, fake_lines={40: "lorem ipsum"})
    actual_lines = result.get_lines()
    assert actual_lines == [40]
    assert result.to_json() == {
        "score": 0.75,
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "score": 0.5,
                "lineTypeCount": {"result": 1},
                "lines": [
                    {
                        "score": 0.5,
                        "line": 40,
                        "lineText": "lorem ipsum",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ],
            }
        ],
        "path": "test.txt",
    }


def test_add_result_twice_when_combining_sources(create_result):
    result = create_result("", fake_lines={40: "lorem ipsum"})
    result.add_line(40, 0.01)
    result.lines[40].types.add("context")
    result.add_line(
        40, 0.02
    )  # this should not be the final value because 0.01 is better

    assert result.lines[40].vector_distance == 0.01
    assert "context" in result.lines[40].types


def test_add_context_above_1(create_result, repo):
    query = "QueryTest"
    result = create_result(query)
    result.add_context_lines(-1)
    actual_lines = result.get_lines()
    assert actual_lines == [39, 40]
    assert result.to_json() == {
        "score": 0.75,
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "score": 0.5,
                "lineTypeCount": {"context": 1, "result": 1},
                "lines": [
                    {
                        "score": 0.0,
                        "line": 39,
                        "lineText": "fake line 39",
                        "resultTypes": [
                            "context",
                        ],
                    },
                    {
                        "score": 0.5,
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ],
            }
        ],
        "path": "test.txt",
    }


def test_add_context_above_2(create_result, repo):
    query = "QueryTest"
    result = create_result(query)
    result.add_line(20, 0.5)
    result.add_context_lines(-1)
    actual_lines = result.get_lines()
    assert actual_lines == [19, 20, 39, 40]
    assert result.to_json() == {
        "score": 0.75,
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "score": 0.5,
                "lineTypeCount": {"context": 1, "result": 1},
                "lines": [
                    {
                        "score": 0.0,
                        "line": 19,
                        "lineText": "fake line 19",
                        "resultTypes": [
                            "context",
                        ],
                    },
                    {
                        "score": 0.5,
                        "line": 20,
                        "lineText": "fake line 20",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ],
            },
            {
                "score": 0.5,
                "lineTypeCount": {"context": 1, "result": 1},
                "lines": [
                    {
                        "score": 0.0,
                        "line": 39,
                        "lineText": "fake line 39",
                        "resultTypes": [
                            "context",
                        ],
                    },
                    {
                        "score": 0.5,
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ],
            },
        ],
        "path": "test.txt",
    }


def test_add_context_below_1(create_result, repo):
    query = "QueryTest"
    result = create_result(query)
    result.add_context_lines(1)
    actual_lines = result.get_lines()
    assert actual_lines == [40, 41]
    assert result.to_json() == {
        "score": 0.75,
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "score": 0.5,
                "lineTypeCount": {"context": 1, "result": 1},
                "lines": [
                    {
                        "score": 0.5,
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                    {
                        "score": 0.0,
                        "line": 41,
                        "lineText": "fake line 41",
                        "resultTypes": [
                            "context",
                        ],
                    },
                ],
            },
        ],
        "path": "test.txt",
    }


def test_add_context_below_2(create_result, repo):
    query = "QueryTest"
    result = create_result(query)
    result.add_line(41, 0.5)
    result.add_line(42, 0.5)
    result.add_context_lines(1)
    actual_lines = result.get_lines()
    assert actual_lines == [40, 41, 42, 43]
    assert result.to_json() == {
        "score": 0.75,
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "score": 0.5,
                "lineTypeCount": {"context": 3, "result": 3},
                "lines": [
                    {
                        "score": 0.5,
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                    {
                        "score": 0.5,
                        "line": 41,
                        "lineText": "fake line 41",
                        "resultTypes": [
                            "context",
                            "result",
                        ],
                    },
                    {
                        "score": 0.5,
                        "line": 42,
                        "lineText": "fake line 42",
                        "resultTypes": [
                            "context",
                            "result",
                        ],
                    },
                    {
                        "score": 0.0,
                        "line": 43,
                        "lineText": "fake line 43",
                        "resultTypes": [
                            "context",
                        ],
                    },
                ],
            },
        ],
        "path": "test.txt",
    }


@pytest.mark.parametrize(
    "context_line, expected_lines",
    [
        (-2, [38, 39, 40]),
        (-3, [37, 38, 39, 40]),
        (2, [40, 41, 42]),
        (4, [40, 41, 42, 43, 44]),
    ],
)
def test_adds_correct_context_lines(create_result, context_line, expected_lines):
    result = create_result("")
    result.add_context_lines(context_line)
    actual_lines = result.get_lines()
    assert actual_lines == expected_lines


@pytest.mark.parametrize(
    "first_code_line, first_block_length, second_block_length, gap",
    [
        (3, 3, 2, 1),
        (5, 1, 1, 2),
    ],
)
def test_merges_almost_continuous_code_lines(
    first_code_line,
    first_block_length,
    second_block_length,
    gap,
    create_result,
    repo,
):
    first_code_block_lines = list(
        range(first_code_line, first_code_line + first_block_length)
    )
    bridge_start = first_code_line + first_block_length
    bridge_lines = list(range(bridge_start, bridge_start + gap))
    second_block_start = bridge_start + gap
    second_code_block_lines = list(
        range(second_block_start, second_block_start + second_block_length)
    )
    line_numbers_to_include = first_code_block_lines + second_code_block_lines
    result = create_result(
        "hello",
        lines_to_include=line_numbers_to_include,
    )
    assert result.to_json() == {
        "score": 0.75,
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "score": 0.5,
                "lineTypeCount": {
                    "result": first_block_length + second_block_length,
                    "bridge": gap,
                },
                "lines": [
                    {
                        "score": 0.5,
                        "line": line_number,
                        "lineText": f"fake line {line_number}",
                        "resultTypes": [
                            "result",
                        ],
                    }
                    for line_number in first_code_block_lines
                ]
                + [
                    {
                        "score": 0.0,
                        "line": line_number,
                        "lineText": f"fake line {line_number}",
                        "resultTypes": [
                            "bridge",
                        ],
                    }
                    for line_number in bridge_lines
                ]
                + [
                    {
                        "score": 0.5,
                        "line": line_number,
                        "lineText": f"fake line {line_number}",
                        "resultTypes": [
                            "result",
                        ],
                    }
                    for line_number in second_code_block_lines
                ],
            },
        ],
        "path": "test.txt",
    }
