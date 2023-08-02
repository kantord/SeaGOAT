# pylint: disable=redefined-outer-name, too-few-public-methods
import logging
import multiprocessing
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import appdirs
import pytest
import requests
from click.testing import CliRunner
from git.repo import Repo
from git.util import Actor
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from seagoat.server import get_server_info_file
from seagoat.server import load_server_info
from seagoat.server import start_server
from seagoat.server import wait_for


@pytest.fixture(scope="session", autouse=True)
def suppress_chromadb_logger():
    logging.getLogger("chromadb").setLevel(logging.WARNING)


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


@pytest.fixture(name="server")
def _server(repo):
    server_process = multiprocessing.Process(
        target=start_server, args=(repo.working_dir,)
    )
    server_process.start()

    server_info_file = get_server_info_file(repo.working_dir)
    wait_for(lambda: os.path.exists(server_info_file), 120)

    _, __, ___, server_address = load_server_info(
        get_server_info_file(repo.working_dir)
    )

    retries = Retry(
        total=200, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504]
    )

    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))

    try:
        response = session.get(
            f"{server_address}/query/test", timeout=1
        )  # adjust timeout as needed
        response.raise_for_status()
    except:
        server_process.terminate()
        server_process.join()
        raise

    yield server_address

    server_process.terminate()
    server_process.join()


@pytest.fixture
def mock_server_factory(mocker, repo):
    def _mock_results(results_template):
        results = []
        fake_files = defaultdict(lambda: defaultdict(lambda: ""))

        for filename, lines in results_template:
            for i, line_text in enumerate(lines):
                fake_files[filename][i] = line_text

        for filename, lines in fake_files.items():
            with open(
                Path(repo.working_dir) / filename, "w", encoding="utf-8"
            ) as output_file:
                lines_sorted_by_line_number = sorted(lines.items(), key=lambda x: x[0])
                fake_file_contents = "\n".join(
                    [line for _, line in lines_sorted_by_line_number]
                )
                output_file.write(fake_file_contents)

        for filename, lines in results_template:
            result = {
                "path": filename,
                "full_path": Path(repo.working_dir) / filename,
                "lines": [],
            }
            for i, line_text in enumerate(lines):
                result["lines"].append({"line": i + 1, "line_text": line_text})

            results.append(result)

        return results

    def _mock_server(results_template):
        mocked_results = _mock_results(results_template)
        mocker.patch("seagoat.cli.query_server", return_value=mocked_results)
        mocker.patch(
            "seagoat.cli.load_server_info",
            return_value=(None, None, None, "fake_server_address"),
        )
        mocker.patch(
            "seagoat.cli.get_server_info_file", return_value="fake_server_info_file"
        )
        mocker.patch("os.isatty", return_value=True)

    return _mock_server


class CustomCliRunner(CliRunner):
    def invoke(self, *args, **kwargs):
        kwargs["catch_exceptions"] = False
        result = super().invoke(*args, **kwargs)
        assert result.exception is None
        return result


@pytest.fixture
def runner():
    return CustomCliRunner()
