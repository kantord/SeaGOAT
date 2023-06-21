from codector.file import File


# pylint: disable-next=too-few-public-methods
class Commit:
    def __init__(self, message):
        self.message = message
        self.committed_date = 0


def test_file_returns_global_metadata_1():
    my_file = File("hello.md")
    my_file.add_commit(Commit("First commit for this"))
    my_file.add_commit(Commit("Another commit for this"))

    assert (
        my_file.get_metadata()
        == """###
First commit for this
Another commit for this"""
    )


def test_file_returns_global_metadata_2():
    my_file = File("hello.md")
    my_file.add_commit(Commit("Unrelated commit"))

    assert (
        my_file.get_metadata()
        == """###
Unrelated commit"""
    )
