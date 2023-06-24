import pytest

from codector.engine import Engine


@pytest.fixture(autouse=True)
# pylint: disable=unused-argument
def use_real_db(real_chromadb):
    pass


def test_allows_setting_query(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "lightweight markup language"
    codector.query(my_query)

    assert codector.query_string == my_query


def test_requires_fetching_data(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "lightweight markup language"
    codector.query(my_query)

    assert len(codector.get_results()) == 0


def test_allows_fetching_data(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "lightweight markup language"
    codector.query(my_query)
    codector.fetch()

    assert len(codector.get_results()) > 2


def test_gets_data_using_vector_embeddings_1(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "lightweight markup language"
    codector.query(my_query)
    codector.fetch()

    assert codector.get_results()[0].path == "file1.md"


def test_gets_data_using_vector_embeddings_2(repo):
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
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "tomato pizza"
    codector.query(my_query)
    codector.fetch()

    assert codector.get_results()[0].path == "articles.txt"


def test_considers_filename_in_results(repo):
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
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "tomato pizza"
    codector.query(my_query)
    codector.fetch()

    assert codector.get_results()[0].path == "recipes.txt"


def test_considers_commit_messages(repo):
    repo.add_file_change_commit(
        file_name="vehicles_1.txt",
        contents=".",
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
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "italian pomodoro pie with slices of cured meat"
    codector.query(my_query)
    codector.fetch()

    assert codector.get_results()[0].path == "vehicles_1.txt"


def test_truncates_very_long_lines(repo):
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
    codector = Engine(repo.working_dir)
    codector.analyze_codebase()
    my_query = "tomato pizza"
    codector.query(my_query)
    codector.fetch()

    assert codector.get_results()[0].path == "vehicles.txt"
