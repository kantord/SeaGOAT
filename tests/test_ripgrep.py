import subprocess
from pathlib import Path

import pytest

from seagoat.engine import Engine
from seagoat.repository import Repository
from seagoat.sources.ripgrep import initialize


@pytest.mark.asyncio
async def test_includes_all_matching_lines_from_line(repo):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: Nothing
        2: Battle of Waterloo 1815
        3:
        4: Moon landing 1969
        5: Unrelated data
        6: The first flight of the Wright Brothers 1903
        7: The signing of the Magna Carta 1215
        8: Some other information
        9: The fall of the Berlin Wall 1989
        """,
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "19"
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "events.txt"
    assert set(results[0].get_lines()) == {4, 6, 9}


@pytest.mark.asyncio
async def test_search_is_case_insensitive(repo):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: Nothing
        2: Battle of Waterloo 1815
        3:
        4: Moon landing 1969
        5: Unrelated data
        6: The first flight of the Wright Brothers 1903
        7: The signing of the Magna Carta 1215
        8: Some other information
        9: The fall of the Berlin Wall 1989
        """,
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "UNRELATED"
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "events.txt"
    assert set(results[0].get_lines()) == {5}


@pytest.mark.asyncio
async def test_respects_file_extension_restrictions(repo):
    repo.add_file_change_commit(
        file_name="rock.mp3",
        contents="19",
        commit_message="Add music file",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "19"
    results = await seagoat.query(my_query)

    assert "rock.mp3" not in [result.gitfile.path for result in results]


@pytest.mark.parametrize(
    "context_above,context_below,expected_lines",
    [
        (0, 0, {4, 6, 9}),
        (2, 0, {2, 3, 4, 5, 6, 7, 8, 9}),
        (0, 2, {4, 5, 6, 7, 8, 9, 10, 11}),
        (2, 3, {2, 3, 4, 5, 6, 7, 8, 9, 10, 11}),
    ],
)
@pytest.mark.asyncio
async def test_includes_context_lines_properly(
    repo, context_above, context_below, expected_lines
):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: Nothing
        2: Battle of Waterloo 1815
        3:
        4: Moon landing 1969
        5: Unrelated data
        6: The first flight of the Wright Brothers 1903
        7: The signing of the Magna Carta 1215
        8: Some other information
        9: The fall of the Berlin Wall 1989
        10: Random event
        11: Another unrelated data""",
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "19"
    results = seagoat.query_sync(
        my_query, context_above=context_above, context_below=context_below
    )

    assert results[0].gitfile.path == "events.txt"
    assert set(results[0].get_lines()) == expected_lines


@pytest.mark.asyncio
async def test_ripgrep_respects_custom_ignore_patterns(repo, create_config_file):
    create_config_file({"server": {"ignorePatterns": ["**/events.txt"]}})

    repo.add_file_change_commit(
        file_name="history/files/events.txt",
        contents="Battle of Waterloo 1815",
        commit_message="commit",
    )

    repo.add_file_change_commit(
        file_name="events.txt",
        contents="Moon landing 1969",
        commit_message="Add historical events",
    )

    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "1"
    results = await seagoat.query(my_query)

    results_files = {result.gitfile.path for result in results}
    assert "history/files/events.txt" not in results_files
    assert "events.txt" in results_files


@pytest.mark.asyncio
async def test_filters_stop_words(repo):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: Nothing
        2: Battle of Waterloo 1815
        3:
        4:
        5: that that that
        6:
        7: The signing of the Magna Carta 1215
        8: Some other information
        9: The fall of the Berlin Wall 1989
        """,
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "that this the potato 1989"
    results = await seagoat.query(my_query)

    events_result = next(
        result for result in results if result.gitfile.path == "events.txt"
    )
    assert 5 not in set(events_result.get_lines())


@pytest.mark.asyncio
async def test_does_not_filter_stop_words_if_that_is_all_whats_in_the_query(repo):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: Nothing
        2: Battle of Waterloo 1815
        3:
        4:
        5: that that that
        6:
        7: The signing of the Magna Carta 1215
        8: Some other information
        9: The fall of the Berlin Wall 1989
        """,
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "that this their"
    results = await seagoat.query(my_query)

    events_result = next(
        result for result in results if result.gitfile.path == "events.txt"
    )
    assert set(events_result.get_lines()) == {5}


@pytest.mark.asyncio
async def test_uses_committed_version_of_files_with_uncommitted_changes(repo):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="1: Moon landing 1969\n",
        commit_message="Add historical events",
    )
    # Uncommitted lines after the end of the committed file: results are
    # displayed from the committed version, which has no such lines
    with open(f"{repo.working_dir}/events.txt", "a", encoding="utf-8") as file:
        file.write("2: Nothing\n3: The fall of the Berlin Wall 1989\n")
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    results = await seagoat.query("19")

    assert results[0].gitfile.path == "events.txt"
    assert set(results[0].get_lines()) == {1}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["--version", "--files", "-e"])
async def test_queries_that_look_like_options_are_patterns(repo, query):
    repo.add_file_change_commit(
        file_name="flags.txt",
        contents=f"1: run with {query} to see it\n",
        commit_message="Add flags",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    results = await seagoat.query(query)

    assert "flags.txt" in [result.gitfile.path for result in results]


@pytest.mark.asyncio
@pytest.mark.parametrize("file_name", ["a:b.txt", "-dash.txt", "x:1:y.txt"])
async def test_finds_files_with_unusual_names(repo, file_name):
    # Committed with git itself: GitPython refuses paths containing ":"
    Path(repo.working_dir, file_name).write_text("1: Moon landing 1969\n")
    git = ["git", "-C", repo.working_dir, "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "--", file_name], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "Add file"], check=True)
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    results = await seagoat.query("1969")

    assert file_name in [result.gitfile.path for result in results]


@pytest.mark.asyncio
async def test_searches_files_that_are_not_valid_utf8(repo):
    repo.add_file_change_commit(
        file_name="latin1.txt",
        contents="1: Moon landing 1969, café\n",
        commit_message="Add Latin-1 file",
        encoding="latin-1",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    results = await seagoat.query("1969")

    assert [result.gitfile.path for result in results] == ["latin1.txt"]


@pytest.fixture(name="initialize_ripgrep_source")
def _initialize_ripgrep_source():
    def _initialize(repo):
        path = repo.working_dir
        my_repo = Repository(path)
        my_repo.analyze_files()
        source = initialize(my_repo)

        source["cache_repo"]()

        return source["fetch"]

    return _initialize


@pytest.mark.asyncio
async def test_line_with_three_query_words_beats_lines_with_one(
    repo, initialize_ripgrep_source
):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: moon landing 1969
        2: landing
        3: moon
        4: 1969
        5: moon landing
        """,
        commit_message="Add events",
    )

    fetch = initialize_ripgrep_source(repo)
    results = fetch("moon landing 1969", limit=1)

    assert len(results) == 1
    result = next(iter(results))
    assert result.gitfile.path == "events.txt"
    # Only the line containing all three distinct query words is kept
    assert set(result.lines) == {1}


@pytest.mark.asyncio
async def test_line_with_three_query_words_kept_before_single_word_lines(
    repo, initialize_ripgrep_source
):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: landing
        2: moon
        3: 1969
        4: moon landing 1969
        """,
        commit_message="Add events",
    )

    fetch = initialize_ripgrep_source(repo)
    results = fetch("moon landing 1969", limit=2)

    assert len(results) == 1
    result = next(iter(results))
    # The two kept lines are the three-word line and (tie broken by rg order)
    # the first single-word line; the three-word line must be among them
    assert set(result.lines) == {1, 4}


@pytest.mark.asyncio
async def test_distance_shrinks_with_more_distinct_query_words(
    repo, initialize_ripgrep_source
):
    repo.add_file_change_commit(
        file_name="events.txt",
        contents="""1: moon
        2: moon landing
        3: moon landing 1969
        """,
        commit_message="Add events",
    )

    fetch = initialize_ripgrep_source(repo)
    results = fetch("moon landing 1969", limit=10)

    assert len(results) == 1
    result = next(iter(results))
    # max_vector_distance defaults to 1.5, so a single-word match is 1.2
    assert result.lines[1].vector_distance == pytest.approx(1.2)
    # A two-word match gets half the distance
    assert result.lines[2].vector_distance == pytest.approx(0.6)
    # A three-word match gets a third of the distance
    assert result.lines[3].vector_distance == pytest.approx(0.4)


def test_a_nul_byte_in_another_file_does_not_break_search(repo):
    repo.add_file_change_commit(
        file_name="a.py", contents="def hello():\n    pass\n", commit_message="a"
    )
    repo.add_file_change_commit(
        file_name="b.txt", contents="x nul\x00here\n", commit_message="b"
    )
    engine = Engine(repo.working_dir)
    engine.analyze_codebase()

    results = engine.query_sync("hello")

    assert "a.py" in [result.gitfile.path for result in results]


def test_best_line_in_a_less_important_file_is_found(repo):
    # old.py has the only line with every query word, but new.py is more
    # frecent and has hundreds of one-word matches that ripgrep reads first
    repo.tick_fake_date(days=-50)
    repo.add_file_change_commit(
        file_name="old.py", contents="foo bar baz\n", commit_message="o"
    )
    repo.tick_fake_date(days=50)
    for i in range(5):
        repo.add_file_change_commit(
            file_name="new.py", contents="foo\n" * 300 + f"#{i}\n", commit_message="n"
        )
    engine = Engine(repo.working_dir)
    # No embeddings: ripgrep is the only source, as early in indexing
    engine.analyze_codebase(minimum_chunks_to_analyze=0)

    results = engine.query_sync("foo bar baz", limit_clue=3)

    assert "old.py" in [result.gitfile.path for result in results]
