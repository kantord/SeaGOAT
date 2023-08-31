from pathlib import Path

from seagoat.result import Result
from tests.conftest import pytest


@pytest.fixture(name="create_result")
def create_result_(repo):
    def noop():
        pass

    cleanup = {"cleanup": noop}

    def result_factory(fake_lines=None):
        if fake_lines is None:
            fake_lines = {}
        test_file_path = Path(repo.working_dir) / "test.txt"
        with test_file_path.open("w", encoding="utf-8") as output_file:
            fake_content = "".join(
                f"{fake_lines[i]}\n" if i in fake_lines else f"fake line {i}\n"
                for i in range(1, 100)
            )
            output_file.write(fake_content)

        result = Result("test.txt", test_file_path)
        result.add_line(40, 0.5)

        cleanup["cleanup"] = test_file_path.unlink

        return result

    yield result_factory

    cleanup["cleanup"]()


def test_get_lines_without_context(create_result, repo):
    query = "famous typographic sample text"
    result = create_result(fake_lines={40: "lorem ipsum"})
    actual_lines = result.get_lines(query)
    assert actual_lines == [40]
    assert result.to_json(query) == {
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "lines": [
                    {
                        "line": 40,
                        "lineText": "lorem ipsum",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ]
            }
        ],
        "path": "test.txt",
    }


def test_add_result_twice_when_combining_sources(create_result):
    result = create_result(fake_lines={40: "lorem ipsum"})
    result.add_line(40, 0.01)
    result.lines[40].types.add("context")
    result.add_line(
        40, 0.02
    )  # this should not be the final value because 0.01 is better

    assert result.lines[40].vector_distance == 0.01
    assert "context" in result.lines[40].types


def test_add_context_above_1(create_result, repo):
    query = "QueryTest"
    result = create_result()
    result.add_context_lines(-1)
    actual_lines = result.get_lines(query)
    assert actual_lines == [39, 40]
    assert result.to_json(query) == {
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "lines": [
                    {
                        "line": 39,
                        "lineText": "fake line 39",
                        "resultTypes": [
                            "context",
                        ],
                    },
                    {
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ]
            }
        ],
        "path": "test.txt",
    }


def test_add_context_above_2(create_result, repo):
    query = "QueryTest"
    result = create_result()
    result.add_line(20, 0.5)
    result.add_context_lines(-1)
    actual_lines = result.get_lines(query)
    assert actual_lines == [19, 20, 39, 40]
    assert result.to_json(query) == {
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "lines": [
                    {
                        "line": 19,
                        "lineText": "fake line 19",
                        "resultTypes": [
                            "context",
                        ],
                    },
                    {
                        "line": 20,
                        "lineText": "fake line 20",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ]
            },
            {
                "lines": [
                    {
                        "line": 39,
                        "lineText": "fake line 39",
                        "resultTypes": [
                            "context",
                        ],
                    },
                    {
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                ]
            },
        ],
        "path": "test.txt",
    }


def test_add_context_below_1(create_result, repo):
    query = "QueryTest"
    result = create_result()
    result.add_context_lines(1)
    actual_lines = result.get_lines(query)
    assert actual_lines == [40, 41]
    assert result.to_json(query) == {
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "lines": [
                    {
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                    {
                        "line": 41,
                        "lineText": "fake line 41",
                        "resultTypes": [
                            "context",
                        ],
                    },
                ]
            },
        ],
        "path": "test.txt",
    }


def test_add_context_below_2(create_result, repo):
    query = "QueryTest"
    result = create_result()
    result.add_line(41, 0.5)
    result.add_line(42, 0.5)
    result.add_context_lines(1)
    actual_lines = result.get_lines(query)
    assert actual_lines == [40, 41, 42, 43]
    assert result.to_json(query) == {
        "fullPath": str(Path(repo.working_dir) / "test.txt"),
        "blocks": [
            {
                "lines": [
                    {
                        "line": 40,
                        "lineText": "fake line 40",
                        "resultTypes": [
                            "result",
                        ],
                    },
                    {
                        "line": 41,
                        "lineText": "fake line 41",
                        "resultTypes": [
                            "context",
                            "result",
                        ],
                    },
                    {
                        "line": 42,
                        "lineText": "fake line 42",
                        "resultTypes": [
                            "context",
                            "result",
                        ],
                    },
                    {
                        "line": 43,
                        "lineText": "fake line 43",
                        "resultTypes": [
                            "context",
                        ],
                    },
                ]
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
    result = create_result()
    result.add_context_lines(context_line)
    actual_lines = result.get_lines("")
    assert actual_lines == expected_lines
