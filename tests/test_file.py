from codector.file import File


def test_file_returns_global_metadata_1():
    my_file = File("hello.md")
    my_file.add_commit_message("First commit for this")
    my_file.add_commit_message("Another commit for this")

    assert (
        my_file.get_metadata()
        == """###
First commit for this
Another commit for this"""
    )


def test_file_returns_global_metadata_2():
    my_file = File("hello.md")
    my_file.add_commit_message("Unrelated commit")

    assert (
        my_file.get_metadata()
        == """###
Unrelated commit"""
    )
