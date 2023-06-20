from codector.library import Codector


def test_version_method_returns_poetry_package_version():
    codector = Codector()
    assert codector.version() == "0.1.0"


def test_has_an_is_ready_method_that_returns_false():
    codector = Codector()
    assert not codector.is_ready()
