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
