import pytest

from codector.engine import Engine


@pytest.fixture(autouse=True)
# pylint: disable=unused-argument
def use_real_db(real_chromadb):
    pass


def test_allows_setting_query(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_files()
    my_query = "lightweight markup language"
    codector.query(my_query)

    assert codector.query_string == my_query


def test_requires_fetching_data(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_files()
    my_query = "lightweight markup language"
    codector.query(my_query)

    assert len(codector.get_results()) == 0


def test_allows_fetching_data(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_files()
    my_query = "lightweight markup language"
    codector.query(my_query)
    codector.fetch()

    assert len(codector.get_results()) > 2


def test_gets_data_using_vector_embeddings_1(repo):
    codector = Engine(repo.working_dir)
    codector.analyze_files()
    my_query = "lightweight markup language"
    codector.query(my_query)
    codector.fetch()

    assert codector.get_results()[0].path == "file1.md"


def test_gets_data_using_vector_embeddings_2(repo):
    repo.add_file_change_commit(
        file_name="recipes_1.txt",
        contents="Italian food recipes",
        author=repo.actors["John Doe"],
        commit_message="Add italian food recipes",
    )
    repo.add_file_change_commit(
        file_name="recipes_2.txt",
        contents="Mexican food recipes",
        author=repo.actors["John Doe"],
        commit_message="Add mexican food recipes",
    )
    repo.add_file_change_commit(
        file_name="recipes_2.txt",
        contents="Mexican food recipes taco",
        author=repo.actors["John Doe"],
        commit_message="Update mexican food recipes",
    )
    codector = Engine(repo.working_dir)
    codector.analyze_files()
    my_query = "pizza"
    codector.query(my_query)
    codector.fetch()

    assert codector.get_results()[0].path == "recipes_1.txt"
