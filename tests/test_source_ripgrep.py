from hypothesis import given, settings
from hypothesis import strategies as st

from seagoat.repository import Repository
from seagoat.sources.ripgrep import (
    STOP_WORDS,
    initialize,
    map_global_line_to_file,
    query_terms,
    run_ripgrep,
)
from tests.test_ripgrep import pytest


@pytest.fixture(name="initialize_source")
def _initialize_source():
    def _initalize(repo):
        path = repo.working_dir
        my_repo = Repository(path)
        my_repo.analyze_files()
        source = initialize(my_repo)

        source["cache_repo"]()

        return source["fetch"]

    return _initalize


def test_fetch_and_initialize(repo, initialize_source):
    contents = """
234
hello foo bar baz
hello foo bar baz 23

234234
345 adaf
2345234523452345235
2345
"""
    repo.add_file_change_commit(
        file_name="file1.txt",
        contents=contents,
        commit_message="Initial commit for text file",
    )

    fetch = initialize_source(repo)
    fetched_results = fetch("[0-9]{2,10}", limit=400)

    assert len(fetched_results) == 1
    file = next(iter(fetched_results))
    assert file.gitfile.path == "file1.txt"
    assert set(file.lines) == {2, 4, 6, 7, 8, 9}


def test_whitespace_is_used_as_or_operator(repo, initialize_source):
    contents = """
234
hello foo bar baz
hello foo bar baz 23

234234
345 adaf
2345234523452345235
2345
baz
bar
b3
"""
    repo.add_file_change_commit(
        file_name="file1.txt",
        contents=contents,
        commit_message="Initial commit for text file",
    )

    fetch = initialize_source(repo)
    fetched_results = fetch("[0-9]{2,10} baz bar b[0-9]", limit=100)

    assert len(fetched_results) == 1
    result = next(iter(fetched_results))
    assert result.gitfile.path == "file1.txt"
    assert set(result.lines) == {
        2,
        3,
        4,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
    }


def test_exact_match_bonus_for_lines_with_all_terms(repo, initialize_source):
    contents = """zorch flib quux here
zorch
"""
    repo.add_file_change_commit(
        file_name="file1.txt",
        contents=contents,
        commit_message="Initial commit",
    )

    fetch = initialize_source(repo)
    results = fetch("zorch flib quux", limit=100)

    assert len(results) == 1
    result = next(iter(results))

    all_terms_line = result.lines[1]
    single_term_line = result.lines[2]
    assert all_terms_line.get_score() < single_term_line.get_score()


def test_how_is_removed_as_stop_word(repo, initialize_source):
    contents = """parse
"""
    repo.add_file_change_commit(
        file_name="file1.txt",
        contents=contents,
        commit_message="Initial commit",
    )

    fetch = initialize_source(repo)
    result_with_how = next(iter(fetch("How parse", limit=100)))
    result_without_how = next(iter(fetch("parse", limit=100)))

    assert (
        result_with_how.lines[1].get_score() == result_without_how.lines[1].get_score()
    )


@pytest.mark.parametrize("query", ["matcher\x00", "matcher\ud800"])
def test_query_with_invalid_characters_still_finds_matches(
    repo, initialize_source, query
):
    contents = """matcher line
"""
    repo.add_file_change_commit(
        file_name="file1.txt",
        contents=contents,
        commit_message="Initial commit",
    )

    fetch = initialize_source(repo)
    results = fetch(query, limit=100)

    assert len(results) == 1
    result = next(iter(results))
    assert result.gitfile.path == "file1.txt"
    assert 1 in result.lines


def _clean_token(token):
    cleaned = []
    for char in token:
        if char == "\x00":
            continue
        try:
            char.encode("utf-8")
        except UnicodeEncodeError:
            continue
        cleaned.append(char)
    return "".join(cleaned)


@given(st.text())
@settings(deadline=None, max_examples=50)
def test_query_terms_properties(query_text):
    cleaned_tokens = [
        cleaned
        for cleaned in (_clean_token(token) for token in query_text.split())
        if cleaned
    ]
    terms = query_terms(query_text)

    for term in terms:
        assert term
        assert term.split() == [term]
        term.encode("utf-8")
        assert "\x00" not in term
        assert any(term in cleaned for cleaned in cleaned_tokens)

    if cleaned_tokens:
        assert terms

    if any(term.lower() in STOP_WORDS for term in terms):
        assert all(cleaned.lower() in STOP_WORDS for cleaned in cleaned_tokens)


def test_path_only_term_does_not_match(repo, initialize_source):
    """A term that only appears in the file path must not return the file."""
    repo.add_file_change_commit(
        file_name="special_code.py",
        contents="1: nothing relevant here\n",
        commit_message="Add special code file",
    )

    fetch = initialize_source(repo)
    results = fetch("special", limit=10)

    assert "special_code.py" not in [result.gitfile.path for result in results]


def test_caret_anchors_at_start_of_line(repo, initialize_source):
    # Line 2's text starts with "def", so "^def" must anchor at the start of
    # the line text (not at the path, as the old NUL-separated cache did).
    repo.add_file_change_commit(
        file_name="code.py",
        contents="something\ndef my_function():\n   return 1\n",
        commit_message="Add code",
    )

    fetch = initialize_source(repo)
    results = fetch("^def", limit=10)

    assert len(results) == 1
    result = next(iter(results))
    assert result.gitfile.path == "code.py"
    assert set(result.lines) == {2}


@pytest.mark.parametrize(
    "query,contents",
    [
        ("how to change the allowed file types ?", "1: allowed types here\n"),
        ("foo (", "1: hello foo world\n"),
        ("*", "1: a * b\n"),
    ],
)
def test_invalid_regex_queries_still_return_matches(
    repo, initialize_source, query, contents
):
    repo.add_file_change_commit(
        file_name="target.py",
        contents=contents,
        commit_message="Add target file",
    )

    fetch = initialize_source(repo)
    results = fetch(query, limit=10)

    assert "target.py" in [result.gitfile.path for result in results]


@given(st.lists(st.integers(0, 20), min_size=1))
def test_global_line_mapping_round_trips(line_counts):
    cumulative = []
    total = 0
    for count in line_counts:
        total += count
        cumulative.append(total)

    for global_line in range(1, total + 1):
        file_index, local_line = map_global_line_to_file(cumulative, global_line)
        assert 0 <= file_index < len(line_counts)
        assert 1 <= local_line <= line_counts[file_index]
        assert sum(line_counts[:file_index]) + local_line == global_line


@given(
    term=st.text(
        alphabet=st.characters(exclude_categories=["Cs"], exclude_characters="\x00"),
        min_size=1,
    )
)
@settings(deadline=None, max_examples=30)
def test_ripgrep_term_runner_never_raises(term):
    cache_text = "alpha line\nbeta line\n"
    result = run_ripgrep(cache_text, [term], 5)
    assert isinstance(result, list)
    assert all(isinstance(line, int) for line, _ in result)
