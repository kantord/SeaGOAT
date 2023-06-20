import os
import tempfile
import shutil
from datetime import datetime, timedelta, timezone
import pytest
from git import Repo, Actor


@pytest.fixture
def tmp():
    new_directory = tempfile.mkdtemp()
    yield new_directory
    shutil.rmtree(new_directory)


@pytest.fixture
def repo(tmp):
    git_repo = Repo.init(tmp)
    dates = [datetime.now(timezone.utc) - timedelta(days=i) for i in range(5)]
    file_changes = [
        {
            "name": "file1.md",
            "contents": [
                "# Markdown file\nThis is an example Markdown file.",
                "# Markdown file\nThis is an example Markdown file. Updated.",
            ],
            "authors": [
                Actor("John Doe", "jdoe@example.com"),
                Actor("Alice Smith", "asmith@example.com"),
            ],
            "commit_messages": [
                "Initial commit for Markdown file",
                "Update to Markdown file",
            ],
        },
        {
            "name": "file2.py",
            "contents": [
                "# This is an example Python file",
                "# This is an updated example Python file",
            ],
            "authors": [
                Actor("Alice Smith", "asmith@example.com"),
                Actor("Charlie Brown", "cbrown@example.com"),
            ],
            "commit_messages": [
                "Initial commit for Python file",
                "Update to Python file",
            ],
        },
        {
            "name": "file3.py",
            "contents": ["# This is another example Python file"],
            "authors": [Actor("Charlie Brown", "cbrown@example.com")],
            "commit_messages": ["Initial commit for another Python file"],
        },
        {
            "name": "file4.js",
            "contents": [
                "// This is an example JavaScript file",
                "// This is an updated example JavaScript file",
                "// This is a second updated example JavaScript file",
            ],
            "authors": [
                Actor("John Doe", "jdoe@example.com"),
                Actor("Alice Smith", "asmith@example.com"),
                Actor("Charlie Brown", "cbrown@example.com"),
            ],
            "commit_messages": [
                "Initial commit for JavaScript file",
                "Update to JavaScript file",
                "Second update to JavaScript file",
            ],
        },
    ]

    for file_change in file_changes:
        for i in range(len(file_change["contents"])):
            with open(os.path.join(tmp, file_change["name"]), "w", encoding="utf-8") as output_file:
                output_file.write(file_change["contents"][i])

            git_repo.index.add([file_change["name"]])
            author = file_change["authors"][i]
            git_repo.index.commit(
                file_change["commit_messages"][i],
                author=author,
                committer=author,
                author_date=dates[i],
                commit_date=dates[i],
            )

    yield git_repo
