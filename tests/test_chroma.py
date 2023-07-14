# pylint: disable=protected-access
import pytest

from seagoat.engine import Engine
from tests.test_repository import patch


@pytest.fixture(autouse=True)
# pylint: disable-next=unused-argument
def use_real_db(real_chromadb):
    pass


@pytest.mark.run(order=-1)
def test_requires_fetching_data(repo):
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "lightweight markup language"
    seagoat.query(my_query)

    assert len(seagoat.get_results()) == 0


@pytest.mark.asyncio
@pytest.mark.run(order=-1)
async def test_gets_data_using_vector_embeddings(repo):
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "lightweight markup language"
    seagoat.query(my_query)
    await seagoat.fetch()

    # Tests that results are sorted according to relevance
    assert seagoat.get_results()[0].path == "file1.md"

    # Tests that results are grouped by file
    assert len(set(result.path for result in seagoat.get_results())) == len(
        list(seagoat.get_results())
    )

    # Tests that file lines are included for each result
    assert all(1 in result.get_lines(my_query) for result in seagoat.get_results())


@pytest.mark.run(order=-1)
def test_allows_fetching_data_synchronously(repo):
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
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "tomato pizza"
    seagoat.query(my_query)
    seagoat.fetch_sync()

    assert seagoat.get_results()[0].path == "articles.txt"


@pytest.mark.asyncio
@pytest.mark.run(order=-1)
async def test_considers_filename_in_results(repo):
    repo.add_file_change_commit(
        file_name="recipes.txt",
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
    my_query = "tomato pizza"
    seagoat.query(my_query)
    await seagoat.fetch()

    assert seagoat.get_results()[0].path == "recipes.txt"


@pytest.mark.asyncio
@pytest.mark.run(order=-1)
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
    seagoat.query(my_query)
    await seagoat.fetch()

    assert seagoat.get_results()[0].path == "vehicles_1.txt"


@pytest.mark.asyncio
@pytest.mark.run(order=-1)
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
    seagoat.query(my_query)
    await seagoat.fetch()

    assert seagoat.get_results()[0].path == "vehicles.txt"


@pytest.mark.asyncio
@pytest.mark.run(order=-1)
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
    seagoat.query(my_query)
    await seagoat.fetch()

    assert seagoat.get_results()[0].path == "devices.txt"
    assert set(seagoat.get_results()[0].get_lines(my_query)) == {1, 2, 4, 6, 7, 8, 9}


@pytest.mark.asyncio
@pytest.mark.run(order=-1)
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
        12:
        13:
        14:
        """,
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()
    my_query = "apple iphone 12"
    seagoat.query(my_query)
    await seagoat.fetch()

    assert seagoat.get_results()[0].path == "devices.txt"
    assert set(seagoat.get_results()[0].get_lines(my_query)) == {7}


@pytest.mark.asyncio
@pytest.mark.run(order=-1)
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
        seagoat1.query("pomodoro spaghetti")
        await seagoat1.fetch()
        assert mock_add_to_collection.call_count > 2
        assert seagoat1.get_results()[0].path == "articles.txt"
        del seagoat1

    seagoat2 = Engine(repo.working_dir)
    with patch.object(
        seagoat2, "_add_to_collection", wraps=seagoat2._add_to_collection
    ) as mock_add_to_collection:
        seagoat2.analyze_codebase()
        seagoat2.query("pomodoro spaghetti")
        await seagoat2.fetch()
        assert mock_add_to_collection.call_count == 0
        assert seagoat2.get_results()[0].path == "articles.txt"
