import pytest

from seagoat.engine import Engine


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
        author=repo.actors["John Doe"],
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "19"
    seagoat.query(my_query)
    await seagoat.fetch()

    assert seagoat.get_results()[0].path == "events.txt"
    assert set(seagoat.get_results()[0].get_lines(my_query)) == {4, 6, 9}


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
        author=repo.actors["John Doe"],
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "UNRELATED"
    seagoat.query(my_query)
    await seagoat.fetch()

    assert seagoat.get_results()[0].path == "events.txt"
    assert set(seagoat.get_results()[0].get_lines(my_query)) == {5}


@pytest.mark.asyncio
async def test_respects_file_extension_restrictions(repo):
    repo.add_file_change_commit(
        file_name="rock.mp3",
        contents="19",
        author=repo.actors["John Doe"],
        commit_message="Add music file",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "19"
    seagoat.query(my_query)
    await seagoat.fetch()

    assert "rock.mp3" not in [result.path for result in seagoat.get_results()]


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
        11: Another unrelated data
        """,
        author=repo.actors["John Doe"],
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "19"
    seagoat.query(my_query)
    seagoat.fetch_sync(context_above=context_above, context_below=context_below)

    assert seagoat.get_results()[0].path == "events.txt"
    assert set(seagoat.get_results()[0].get_lines(my_query)) == expected_lines


@pytest.mark.asyncio
async def test_ripgrep_respects_custom_ignore_patterns(repo, create_config_file):
    create_config_file({"server": {"ignorePatterns": ["**/events.txt"]}})

    repo.add_file_change_commit(
        file_name="history/files/events.txt",
        contents="Battle of Waterloo 1815",
        author=repo.actors["John Doe"],
        commit_message="commit",
    )

    repo.add_file_change_commit(
        file_name="events.txt",
        contents="Moon landing 1969",
        author=repo.actors["John Doe"],
        commit_message="Add historical events",
    )

    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "1"
    seagoat.query(my_query)
    await seagoat.fetch()

    results_files = set(result.path for result in seagoat.get_results())
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
        author=repo.actors["John Doe"],
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "that this the potato 1989"
    seagoat.query(my_query)
    await seagoat.fetch()

    events_result = [
        result for result in seagoat.get_results() if result.path == "events.txt"
    ][0]
    assert 5 not in set(events_result.get_lines(my_query))


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
        author=repo.actors["John Doe"],
        commit_message="Add historical events",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "that this their"
    seagoat.query(my_query)
    await seagoat.fetch()

    events_result = [
        result for result in seagoat.get_results() if result.path == "events.txt"
    ][0]
    assert set(events_result.get_lines(my_query)) == {5}
