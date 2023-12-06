import pytest

from seagoat.engine import Engine


@pytest.mark.asyncio
async def test_simple_regexp(repo):
    repo.add_file_change_commit(
        file_name="line_positions.txt",
        contents="""apple
        orange apple 0
        apple banana
        grape 12

9999999
        """,
        author=repo.actors["John Doe"],
        commit_message="Add fruits data",
    )

    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    my_regex_query = "[0-9]+[0-9]+"
    results = await seagoat.query(my_regex_query)

    assert results[0].gitfile.path == "line_positions.txt"
    assert set(results[0].get_lines()) == {4, 6}


@pytest.mark.asyncio
async def test_regexp_combined_with_chroma(repo):
    repo.add_file_change_commit(
        file_name="line_positions.txt",
        contents="""samsung iphone
        smart apps
        bicycle 12

        foo
        bar
        baz
9999999 apple pie with orange recipe
9999999 banana pie with pear recipe
9999999 kiwi pie with lemon recipe

2345 23452345 2345
2345235 23452345 32
asdf
asdf
asdf
        """,
        author=repo.actors["John Doe"],
        commit_message="Add fruits data",
    )

    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    my_regex_query = "[0-9]+[0-9]+ fruit"
    results = await seagoat.query(my_regex_query)

    assert results[0].gitfile.path == "line_positions.txt"
    assert set(results[0].get_lines()) == {
        1,
        2,
        3,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
    }
