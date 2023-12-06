import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from seagoat.engine import Engine


def normalize_full_paths(data, repo):
    real_repo_path = repo.working_dir
    fake_repo_path = "/path/to/repo"
    deep_copy_of_data = copy.deepcopy(data)
    deep_copy_of_data["fullPath"] = deep_copy_of_data["fullPath"].replace(
        real_repo_path, fake_repo_path
    )

    return deep_copy_of_data


@pytest.fixture(autouse=True)
def use_real_db(real_chromadb):
    pass


@pytest.mark.asyncio
async def test_gets_data_using_vector_embeddings(repo, snapshot):
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "lightweight markup language"
    results = await seagoat.query(my_query)

    # Tests that results are sorted according to relevance
    assert results[0].gitfile.path == "file1.md"

    # Tests that results are grouped by file
    assert len(set(result.gitfile.path for result in results)) == len(list(results))

    # Tests that file lines are included for each result
    assert [
        normalize_full_paths(result.to_json(), repo) for result in results
    ] == snapshot


def test_allows_fetching_data_synchronously(repo):
    repo.add_file_change_commit(
        file_name="articles.txt",
        contents="Italian food recipes, tükörfúrógép, spaghetti, pomodoro, pepperoni\n",
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
        encoding="utf-8",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="Ford",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="motorbike, ford, mercedes\n",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "tomato pizza"
    results = seagoat.query_sync(my_query, limit_clue=33)

    assert results[0].gitfile.path == "articles.txt"


@pytest.mark.asyncio
async def test_considers_filename_in_results(repo):
    repo.add_file_change_commit(
        file_name="cooking_recipes.txt",
        contents="motorbike, ford, mercedes\n",
        author=repo.actors["John Doe"],
        commit_message=".",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="Ford",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="motorbike, ford, mercedes\n",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "dish_recipe.txt"
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "cooking_recipes.txt"


@pytest.mark.asyncio
async def test_considers_commit_messages(repo):
    repo.add_file_change_commit(
        file_name="vehicles_1.txt",
        contents="the the the",
        author=repo.actors["John Doe"],
        commit_message="pizza tomato salami recipe",
    )
    repo.add_file_change_commit(
        file_name="vehicles_2.txt",
        contents=".",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    repo.add_file_change_commit(
        file_name="vehicles_2.txt",
        contents="",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "italian pomodoro pie with slices of cured meat"
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "vehicles_1.txt"


@pytest.mark.asyncio
async def test_truncates_very_long_lines(repo):
    repo.add_file_change_commit(
        file_name="articles.txt",
        contents=f"car {'the a about ' * 40} pizza recipe tomato italian pie\n",
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="Ford tomato",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="motorbike, ford, mercedes with tomato and cheese\n",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "tomato pizza"
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "vehicles.txt"


@pytest.mark.asyncio
async def test_includes_all_matching_lines_from_line(repo):
    repo.add_file_change_commit(
        file_name="devices.txt",
        contents="""1: Nothing
        2: Google Pixel 2 Android
        3:
        4: Mango juice
        5: Fried potatoes
        6: Chicken wings
        7: Apple iPhone 12
        8: Pizza slices with pepperoni
        9: Samsung Galaxy S10
        10:
        11:
        12:
        13:
        14:
        """,
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "smartphone"
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "devices.txt"
    assert set(results[0].get_lines()) == {
        1,
        2,
        4,
        6,
        7,
        8,
        9,
    }


@pytest.mark.asyncio
async def test_exact_matches_have_higher_score(repo):
    repo.add_file_change_commit(
        file_name="devices.txt",
        contents="""1: Nothing
        2: Google Pixel 2 Android
        3:
        4: Mango juice
        5: Fried potatoes
        6: Chicken wings
        7: Apple iPhone 12
        8: Pizza slices with pepperoni
        9: Samsung Galaxy S10
        10:
        11:

        13:
        14:
        """,
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "apple      iphone 12"
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "devices.txt"
    assert set(results[0].get_lines()) == {7, 8, 12}


@pytest.mark.asyncio
async def test_chunks_are_persisted_between_runs(repo):
    repo.add_file_change_commit(
        file_name="articles.txt",
        contents="Italian food recipes, spaghetti, pomodoro, pepperoni\n",
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="Ford",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    repo.add_file_change_commit(
        file_name="vehicles.txt",
        contents="motorbike, ford, mercedes\n",
        author=repo.actors["John Doe"],
        commit_message="Add vehicle information",
    )
    seagoat1 = Engine(repo.working_dir)
    with patch.object(
        seagoat1, "_add_to_collection", wraps=seagoat1._add_to_collection
    ) as mock_add_to_collection:
        seagoat1.analyze_codebase()
        results1 = await seagoat1.query("pomodoro spaghetti")
        assert mock_add_to_collection.call_count > 2
        assert results1[0].gitfile.path == "articles.txt"
        del seagoat1

    seagoat2 = Engine(repo.working_dir)
    with patch.object(
        seagoat2, "_add_to_collection", wraps=seagoat2._add_to_collection
    ) as mock_add_to_collection:
        seagoat2.analyze_codebase()
        results2 = await seagoat2.query("pomodoro spaghetti")
        assert mock_add_to_collection.call_count == 0
        assert results2[0].gitfile.path == "articles.txt"


@pytest.mark.asyncio
async def test_respects_limit_in_chromadb(repo):
    for i in range(100):
        repo.add_file_change_commit(
            file_name="devices2.txt",
            contents="food from an orchard, but not a banana or pear. It's red",
            author=repo.actors["John Doe"],
            commit_message=f"commit {i}",
        )
        repo.tick_fake_date(days=1)
    repo.tick_fake_date(days=1)
    repo.add_file_change_commit(
        file_name="devices.txt",
        contents="""banana, fruit, red, Macintosh, iPhone
        """
        * 6,
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "apple"
    results = await seagoat.query(my_query, limit_clue=5)

    expected_files = {"devices.txt", "devices2.txt"}
    results_files = set(result.gitfile.path for result in results)

    assert expected_files.issubset(results_files)
    result_for_devices_txt = next(
        (result for result in results if result.gitfile.path == "devices.txt"),
        None,
    )
    if result_for_devices_txt:
        assert len(result_for_devices_txt.get_lines()) == 6
    else:
        raise AssertionError("File 'devices.txt' not found in results.")


@pytest.mark.asyncio
async def test_does_not_crash_repo_when_files_are_deleted(repo):
    repo.add_file_change_commit(
        file_name="cooking_recipes.txt",
        contents="motorbike, ford, mercedes\n",
        author=repo.actors["John Doe"],
        commit_message=".",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "dish_recipe.txt"
    await seagoat.query(my_query)
    (Path(repo.working_dir) / "cooking_recipes.txt").unlink()

    seagoat.analyze_codebase()
    await seagoat.query(my_query)


@pytest.mark.asyncio
async def test_custom_ignore_patterns(repo, create_config_file):
    create_config_file(
        {
            "server": {"ignorePatterns": ["**/devices2.txt"]},
        }
    )
    repo.add_file_change_commit(
        file_name="foo/devices2.txt",
        contents="food from an orchard, but not a banana or pear. It's red",
        author=repo.actors["John Doe"],
        commit_message="commit",
    )
    repo.add_file_change_commit(
        file_name="devices.txt",
        contents="""banana, fruit, red, Macintosh, iPhone
        """
        * 6,
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "apple"
    results = await seagoat.query(my_query, limit_clue=5)

    results_files = set(result.gitfile.path for result in results)

    assert "foo/devices2.txt" not in results_files


@pytest.mark.asyncio
async def test_user_defined_execution_provider(repo, create_config_file):
    create_config_file(
        {
            "server": {
                "chroma": {
                    "embeddingFunction": {
                        "name": "ONNXMiniLM_L6_V2",
                        "arguments": {"preferred_providers": ["CPUExecutionProvider"]},
                    },
                }
            }
        }
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "apple"
    seagoat.query_sync(my_query)


@pytest.mark.asyncio
async def test_does_not_crash_when_file_lines_are_removed(repo):
    repo.add_file_change_commit(
        file_name="devices.txt",
        contents="""1: Nothing
        2: Google Pixel 2 Android
        3:
        4: Mango juice
        5: Fried potatoes
        6: Chicken wings
        7: Apple iPhone 12
        8: Pizza slices with pepperoni
        9: Samsung Galaxy S10
        10:
        11:

        13:
        14:
        """,
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "apple      iphone 12"
    await seagoat.query(my_query)
    repo.add_file_change_commit(
        file_name="devices.txt",
        contents="""1: Nothing
        2: apple
        3:
        4: Mango juice
        """,
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    seagoat.analyze_codebase()
    results = await seagoat.query(my_query)

    assert results[0].gitfile.path == "devices.txt"
