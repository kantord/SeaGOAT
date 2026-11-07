import pytest


@pytest.mark.parametrize(
    "ripgrep_lines, chroma_lines, expected_paths",
    [
        pytest.param(
            {
                "file1.md": [(1, 10.0), (2, 4.0)],
                "file2.md": [(1, 5.0)],
            },
            {
                "file2.md": [(2, 6.0)],
                "file3.md": [(1, 4.5)],
            },
            [
                "file1.md",
                "file3.md",
                "file2.md",
            ],
            id="by-their-closest-line",
        ),
        pytest.param(
            {
                "file1.md": [(1, 10.0)],
                "file2.md": [(1, 15.0)],
            },
            {
                "file3.md": [(1, 5.0)],
            },
            [
                "file3.md",
                "file1.md",
                "file2.md",
            ],
            id="from-both-sources-together",
        ),
    ],
)
def test_sorts_files(
    create_prepared_seagoat, ripgrep_lines, chroma_lines, expected_paths
):
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.query_sync(my_query)

    assert [result.gitfile.path for result in results] == expected_paths


def test_missing_file_in_one_source(create_prepared_seagoat):
    ripgrep_lines = {
        "file1.md": [(1, 10.0)],
        "file2.md": [(1, 5.0)],
    }
    chroma_lines = {
        "file1.md": [(1, 6.0)],
    }
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.query_sync(my_query)

    assert [result.gitfile.path for result in results] == ["file2.md", "file1.md"]


def test_no_lines(create_prepared_seagoat):
    ripgrep_lines = {}
    chroma_lines = {}
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.query_sync(my_query)

    assert results == []


def _add_edits(repo, file_name, count):
    for i in range(count):
        repo.add_file_change_commit(
            file_name=file_name,
            contents=f"Some content {i}",
            commit_message=f"Edit {file_name}",
        )
        repo.tick_fake_date(days=1)


def _sorted_paths(create_prepared_seagoat, ripgrep_lines, chroma_lines):
    my_query = "asdfadsfdfdffdafafdsfadsf"
    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    seagoat.analyze_codebase()
    return [result.gitfile.path for result in seagoat.query_sync(my_query)]


def test_a_better_score_beats_more_edits(create_prepared_seagoat, repo):
    _add_edits(repo, "file_many_edits.md", 20)
    _add_edits(repo, "file_few_edits.md", 1)

    paths = _sorted_paths(
        create_prepared_seagoat,
        {"file_few_edits.md": [(1, 5.0)], "file_many_edits.md": [(1, 6.0)]},
        # A poor match elsewhere in the results must not make that gap count less
        {"random.py": [(1, 60.0)]},
    )

    assert paths[:2] == ["file_few_edits.md", "file_many_edits.md"]


def test_vector_distance_breaks_a_tie_before_edits(create_prepared_seagoat, repo):
    _add_edits(repo, "file_many_edits.md", 20)
    _add_edits(repo, "file_few_edits.md", 1)

    paths = _sorted_paths(
        create_prepared_seagoat,
        {"file_few_edits.md": [(1, 5.0)], "file_many_edits.md": [(1, 5.0)]},
        {"file_few_edits.md": [(2, 7.0)], "file_many_edits.md": [(2, 8.0)]},
    )

    assert paths == ["file_few_edits.md", "file_many_edits.md"]


def test_a_file_with_a_vector_match_wins_a_tie(create_prepared_seagoat, repo):
    _add_edits(repo, "file_many_edits.md", 20)
    _add_edits(repo, "file_few_edits.md", 1)

    paths = _sorted_paths(
        create_prepared_seagoat,
        {"file_few_edits.md": [(1, 5.0)], "file_many_edits.md": [(1, 5.0)]},
        {"file_few_edits.md": [(2, 7.0)]},
    )

    assert paths == ["file_few_edits.md", "file_many_edits.md"]


def test_edits_break_a_tie_when_nothing_else_differs(create_prepared_seagoat, repo):
    _add_edits(repo, "file_many_edits.md", 20)
    _add_edits(repo, "file_few_edits.md", 1)

    paths = _sorted_paths(
        create_prepared_seagoat,
        {"file_few_edits.md": [(1, 5.0)], "file_many_edits.md": [(1, 5.0)]},
        {"file_few_edits.md": [(2, 7.0)], "file_many_edits.md": [(2, 7.0)]},
    )

    assert paths == ["file_many_edits.md", "file_few_edits.md"]
