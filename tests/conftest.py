# pylint: disable=redefined-outer-name

import os
import tempfile
import shutil
from datetime import datetime, timedelta, timezone
from typing import cast
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from git.repo import Repo
from git.util import Actor
import appdirs


class MockRepo(Repo):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake_commit_date = datetime.now(timezone.utc) - timedelta(days=400)
        self.actors = {
            "John Doe": Actor("John Doe", "jdoe@example.com"),
            "Alice Smith": Actor("Alice Smith", "asmith@example.com"),
            "Charlie Brown": Actor("Charlie Brown", "cbrown@example.com"),
        }

    def tick_fake_date(self, days=0, hours=0, minutes=0):
        delta = timedelta(days=days, hours=hours, minutes=minutes)
        self.fake_commit_date += delta

    def add_fake_data(self):
        file_changes = [
            {
                "name": "file1.md",
                "contents": [
                    "# Markdown file\nThis is an example Markdown file.",
                    "# Markdown file\nThis is an example Markdown file. Updated.",
                ],
                "authors": [
                    self.actors["John Doe"],
                    self.actors["Alice Smith"],
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
                    self.actors["Alice Smith"],
                    self.actors["Charlie Brown"],
                ],
                "commit_messages": [
                    "Initial commit for Python file",
                    "Update to Python file",
                ],
            },
            {
                "name": "file3.py",
                "contents": ["# This is another example Python file"],
                "authors": [self.actors["Charlie Brown"]],
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
                    self.actors["John Doe"],
                    self.actors["Alice Smith"],
                    self.actors["Charlie Brown"],
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
                self.add_file_change_commit(
                    file_change["name"],
                    file_change["contents"][i],
                    file_change["authors"][i],
                    file_change["commit_messages"][i],
                )
                self.tick_fake_date(days=1)

    def add_file_change_commit(self, file_name, contents, author, commit_message):
        with open(
            os.path.join(self.working_dir, file_name), "w", encoding="utf-8"
        ) as output_file:
            output_file.write(contents)

        self.index.add([file_name])
        self.index.commit(
            commit_message,
            author=author,
            committer=author,
            author_date=self.fake_commit_date,
            commit_date=self.fake_commit_date,
            skip_hooks=True,
        )


@pytest.fixture
def generate_repo():
    directories_to_delete = []
    repos_to_delete = []

    def repo_generator():
        new_directory = tempfile.mkdtemp()
        directories_to_delete.append(new_directory)
        repo = cast(MockRepo, MockRepo.init(new_directory))
        repo.add_fake_data()
        repos_to_delete.append(repo)

        return repo

    yield repo_generator

    for directory in directories_to_delete:
        try:
            shutil.rmtree(directory)
        except PermissionError:
            pass

    for repo in repos_to_delete:
        repo.close()


@pytest.fixture
def repo(generate_repo):
    repo = generate_repo()
    yield repo


@pytest.fixture(autouse=True)
def run_around_tests():
    yield
    cache_root = Path(appdirs.user_cache_dir("seagoat-pytest"))
    if "RUNNER_TEMP" in os.environ:
        cache_root = Path(os.environ["RUNNER_TEMP"]) / "seagoat-pytest"
    shutil.rmtree(cache_root, ignore_errors=True)


chromadb_patcher = patch("chromadb.Client")


@pytest.fixture(autouse=True)
def mock_chromadb():
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.create_collection.return_value = mock_collection

    chromadb_patcher.start().return_value = mock_client
    yield
    chromadb_patcher.stop()


@pytest.fixture
def real_chromadb():
    chromadb_patcher.stop()
    yield
    chromadb_patcher.start()
