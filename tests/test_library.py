from codector.library import Codector


def test_version_method_returns_poetry_package_version(repo):
    codector = Codector(repo.working_dir)
    assert codector.version() == "0.1.0"


# def test_has_an_is_ready_method_that_returns_false(repo):
#     codector = Codector(repo.worinir)
#     assert not codector.is_ready()
