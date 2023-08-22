# pylint: disable=redefined-outer-name, too-few-public-methods
import logging
import multiprocessing
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from contextlib import contextmanager
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

from seagoat.engine import Engine
from seagoat.result import Result
from seagoat.server import create_app
from seagoat.server import get_server_info_file
from seagoat.server import load_server_info
from seagoat.server import start_server
from seagoat.server import wait_for
from seagoat.sources import chroma
from seagoat.sources import ripgrep


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

    def add_file_change_commit(
        self,
        file_name,
        contents,
        author,
        commit_message,
    ):
        with open(
            os.path.join(self.working_dir, file_name), "w", encoding="utf-8"
        ) as output_file:
            output_file.write(contents)

        self.index.add([file_name])
        return self.index.commit(
            commit_message,
            author=author,
            committer=author,
            author_date=self.fake_commit_date,
            commit_date=self.fake_commit_date,
            skip_hooks=True,
        ).hexsha


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


@pytest.fixture(name="start_server")
def _start_server(repo):
    def _start():
        server_process = multiprocessing.Process(
            target=start_server, args=(repo.working_dir,)
        )
        server_process.start()

        server_info_file = get_server_info_file(repo.working_dir)
        wait_for(lambda: os.path.exists(server_info_file), 120)

        _, __, ___, server_address = load_server_info(
            get_server_info_file(repo.working_dir)
        )

        retries = Retry(total=5, backoff_factor=0.1)

        session = requests.Session()
        session.mount("http://", HTTPAdapter(max_retries=retries))
        session.mount("https://", HTTPAdapter(max_retries=retries))

        response = None
        try:
            response = session.get(f"{server_address}/query/test", timeout=1)
            response.raise_for_status()
        except requests.HTTPError:
            # Make it easier to debug problems by printing error messages
            if response is not None:
                if response.status_code == 500:
                    print("Server responded with a 500 error:")
                    print(response.text)
            server_process.terminate()
            server_process.join()
            raise
        except:
            server_process.terminate()
            server_process.join()
            raise

        def _stop():
            server_process.terminate()
            server_process.join()

        return server_address, _stop

    yield _start


@pytest.fixture(name="server")
def _server(start_server):
    server_address, stop_server = start_server()
    yield server_address
    stop_server()


@pytest.fixture
def init_server_mock(mocker):
    def _init_server_mock():
        mocker.patch(
            "seagoat.cli.load_server_info",
            return_value=(None, None, None, "fake_server_address"),
        )
        mocker.patch(
            "seagoat.cli.get_server_info_file", return_value="fake_server_info_file"
        )
        mocker.patch("os.isatty", return_value=True)

    return _init_server_mock


@pytest.fixture
def mock_server_factory(mocker, repo, init_server_mock):
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
                "fullPath": Path(repo.working_dir) / filename,
                "lines": [],
            }
            for i, line_text in enumerate(lines):
                result["lines"].append(
                    {
                        "line": i + 1,
                        "lineText": line_text,
                        "resultTypes": ["result"]
                        if "context line" not in line_text
                        else ["context"],
                    }
                )

            results.append(result)

        return results

    def _mock_server(results_template, manually_mock_request=False):
        init_server_mock()
        mocked_results = _mock_results(results_template)

        if not manually_mock_request:
            mocker.patch("seagoat.cli.query_server", return_value=mocked_results)

    return _mock_server


@pytest.fixture
def mock_server_error_factory(mocker, init_server_mock):
    def _mock_error_response(error_message, code):
        error_response = {
            "code": code,
            "error": {"type": "Internal Server Error", "message": error_message},
        }

        mocked_response = MagicMock()

        mocked_response.json.return_value = error_response

        return mocked_response

    def _mock_server_error(error_message, code, manually_mock_request=False):
        init_server_mock()
        mocked_error_response = _mock_error_response(error_message, code)

        if not manually_mock_request:
            mocker.patch("seagoat.cli.requests.get", return_value=mocked_error_response)

    return _mock_server_error


class CustomCliRunner(CliRunner):
    def invoke(self, *args, expect_errors=False, **kwargs):
        kwargs["catch_exceptions"] = False
        result = super().invoke(*args, **kwargs)
        if not expect_errors:
            assert result.exception is None
        return result


@pytest.fixture
def runner():
    return CustomCliRunner()


@pytest.fixture
def runner_with_error():
    return CliRunner(mix_stderr=False)


@pytest.fixture
def app(repo):
    app = create_app(repo.working_dir)
    yield app


@pytest.fixture
def client(repo):
    mock_queue = MagicMock()

    with patch("seagoat.server.TaskQueue", mock_queue):
        app = create_app(repo.working_dir)
        app.config["TESTING"] = True
        app.extensions["task_queue"] = mock_queue
        client = app.test_client()
        # pylint: disable=protected-access
        client._mock_queue = mock_queue  # type: ignore

        yield client


@pytest.fixture
def mock_queue(client):
    # pylint: disable=protected-access
    yield client._mock_queue


@pytest.fixture
def managed_process():
    processes = []

    @contextmanager
    def _process(*args, **kwargs):
        proc = subprocess.Popen(*args, **kwargs)
        processes.append(proc)
        try:
            yield proc
        finally:
            proc.terminate()
            proc.wait()
            processes.remove(proc)

    yield _process

    for proc in processes:
        proc.terminate()
        proc.wait()


@contextmanager
def mock_sources_context(repo, ripgrep_lines, chroma_lines):
    # pylint: disable-next=unused-argument
    def noop(*args, **kwargs):
        pass

    def create_mock_fetch(repo, file_lines):
        def mock_fetch(_, __):
            results = []
            for file_path, lines in file_lines.items():
                full_path = Path(repo.working_dir) / file_path
                result = Result(path=file_path, full_path=full_path)
                for line, vector_distance in lines:
                    result.add_line(line=line, vector_distance=vector_distance)
                results.append(result)
            return results

        return mock_fetch

    for file_path in set(list(ripgrep_lines.keys()) + list(chroma_lines.keys())):
        repo.add_file_change_commit(
            file_name=file_path,
            contents="\n" * 50,
            author=repo.actors["John Doe"],
            commit_message=f"Add {file_path}",
        )

    with patch.object(ripgrep, "initialize") as mock_ripgrep, patch.object(
        chroma, "initialize"
    ) as mock_chroma:
        mock_ripgrep.return_value = {
            "fetch": create_mock_fetch(repo, ripgrep_lines),
            "cache_chunk": noop,
        }
        mock_chroma.return_value = {
            "fetch": create_mock_fetch(repo, chroma_lines),
            "cache_chunk": noop,
        }
        yield


@pytest.fixture(name="create_prepared_seagoat")
def _create_prepared_seagoat(repo):
    def _prepared_seagoat(query, ripgrep_lines, chroma_lines):
        with mock_sources_context(repo, ripgrep_lines, chroma_lines):
            seagoat = Engine(repo.working_dir)
            seagoat.analyze_codebase()
            seagoat.query(query)
            seagoat.fetch_sync()
            return seagoat

    return _prepared_seagoat
