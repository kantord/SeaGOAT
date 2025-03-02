import logging
import multiprocessing
import os
import shutil
import signal
import subprocess
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import appdirs
import orjson
import pytest
import requests
import yaml
from click.testing import CliRunner
from git.repo import Repo
from git.util import Actor
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from seagoat.engine import Engine
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.server import create_app, start_server
from seagoat.sources import chroma, ripgrep
from seagoat.utils.config import GLOBAL_CONFIG_FILE
from seagoat.utils.server import ServerDoesNotExist, get_server_info
from seagoat.utils.wait import wait_for

try:
    from pytest_cov.embed import cleanup_on_sigterm
except ImportError:
    pass
else:
    cleanup_on_sigterm()


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
                    (
                        "# Markdown file\nThis is an example Markdown file. Updated. \n"
                        + "HTML is for markup, but it's complicated. Markdown is simpler."
                    ),
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
            {
                "name": "file4.md",
                "contents": [
                    "// This is an example JavaScript file",
                    "// This is an example JavaScript file 2",
                    "// This is an updated example JavaScript file",
                    "// This is a second updated example JavaScript file",
                ],
                "authors": [
                    self.actors["John Doe"],
                    self.actors["John Doe"],
                    self.actors["Alice Smith"],
                    self.actors["Charlie Brown"],
                ],
                "commit_messages": [
                    "Initial commit for JavaScript file",
                    "Initial commit for JavaScript file 2",
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
        file_name: str,
        contents: str,
        author: Actor,
        commit_message: str,
        encoding="utf-8",
    ) -> str:
        # Create parent directory if it doesn't exist:
        parent_folder = os.path.dirname(os.path.join(self.working_dir, file_name))
        if parent_folder:
            os.makedirs(parent_folder, exist_ok=True)

        file_path = os.path.join(self.working_dir, file_name)

        with open(file_path, "w", encoding=encoding) as output_file:
            output_file.write(contents)
        self.index.add([file_name])

        return self._commit_changes(commit_message, author)

    def _commit_changes(self, commit_message: str, author: Actor) -> str:
        return self.index.commit(
            commit_message,
            author=author,
            committer=author,
            author_date=self.fake_commit_date,
            commit_date=self.fake_commit_date,
            skip_hooks=True,
        ).hexsha

    def add_file_delete_commit(
        self,
        file_name: str,
        author: Actor,
        commit_message: str,
    ) -> str:
        file_path = os.path.join(self.working_dir, file_name)

        os.unlink(file_path)
        self.index.remove(file_name)

        return self._commit_changes(commit_message, author)


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
            shutil.rmtree(directory, ignore_errors=True)
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


def _get_multiprocessing_context():
    if os.name == "nt":
        return multiprocessing.get_context("spawn")
    return multiprocessing.get_context("forkserver")


@pytest.fixture(name="start_server", scope="session")
def _start_server():
    def _start(repo_path: str):
        context = _get_multiprocessing_context()
        server_process = context.Process(
            target=start_server, args=(repo_path,), daemon=True
        )
        server_process.start()

        def make_sure_server_is_running():
            try:
                get_server_info(repo_path)
                return True

            except Exception:
                return False

        wait_for(make_sure_server_is_running, timeout=3.0)

        try:
            server_info = get_server_info(repo_path)
        except ServerDoesNotExist as error:
            server_process.kill()
            raise ServerDoesNotExist(
                f"Server info for {repo_path} not found."
            ) from error

        server_address = server_info["address"]

        # type ignored because it is errounously marked as int, it is float
        # as per the official documentation
        retries = Retry(total=5, backoff_factor=0.1)  # type: ignore

        session = requests.Session()
        session.mount("http://", HTTPAdapter(max_retries=retries))
        session.mount("https://", HTTPAdapter(max_retries=retries))

        def _stop():
            try:
                if server_process.pid is not None:
                    os.kill(server_process.pid, signal.SIGTERM)
                server_process.join()
            except ProcessLookupError:
                pass

        response = None
        try:
            response = session.get(f"{server_address}/status", timeout=1)
            response.raise_for_status()
        except requests.HTTPError:
            # Make it easier to debug problems by printing error messages
            if response is not None:
                if response.status_code == 500:
                    print("Server responded with a 500 error:")
                    print(response.text)
            _stop()
            raise
        except:
            _stop()
            raise

        return server_address, _stop

    yield _start


@pytest.fixture(name="server")
def _server(start_server, repo):
    server_address, stop_server = start_server(str(repo.working_dir))
    yield server_address
    stop_server()


@pytest.fixture
def init_server_mock(mocker):
    def _init_server_mock():
        mocker.patch(
            "seagoat.cli.get_server_info",
            return_value={"address": ""},
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
                "blocks": [{"lines": [], "lineTypeCount": {"result": 0, "context": 0}}],
            }
            for i, line_text in enumerate(lines):
                is_context_line = "context line" in line_text
                result["blocks"][0]["lines"].append(
                    {
                        "line": i + 1,
                        "lineText": line_text,
                        "resultTypes": ["result"] if is_context_line else ["context"],
                    }
                )
                result["blocks"][0]["lineTypeCount"][
                    "context" if is_context_line else "result"
                ] += 1

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
            "error": {
                "type": "Internal Server Error",
                "message": error_message,
            },
        }

        mocked_response = MagicMock()

        mocked_response.text = orjson.dumps(error_response)

        return mocked_response

    def _mock_server_error(error_message, code, manually_mock_request=False):
        init_server_mock()
        mocked_error_response = _mock_error_response(error_message, code)

        if not manually_mock_request:
            mocker.patch(
                "seagoat.cli.requests.post", return_value=mocked_error_response
            )

    return _mock_server_error


class CustomCliRunner(CliRunner):
    def invoke(self, *args, expect_errors=False, **kwargs):
        kwargs["catch_exceptions"] = False
        result = super().invoke(*args, **kwargs)
        if not expect_errors:
            assert result.exception is None
        return result


@pytest.fixture
def runner(mock_halo):
    return CustomCliRunner()


@pytest.fixture
def mock_halo(mocker):
    mocker.patch("seagoat.cli.Halo")

    yield


@pytest.fixture
def runner_with_error(mocker, mock_halo):
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

        client._mock_queue = mock_queue  # type: ignore

        yield client


@pytest.fixture
def mock_queue(client):
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
    def noop(*args, **kwargs):
        pass

    def create_mock_query(repo, file_lines):
        def mock_query(_, __):
            results = []
            repository = Repository(repo.working_dir)
            repository.analyze_files()
            for file_path, lines in file_lines.items():
                gitfile = repository.get_file(file_path)
                result = Result("", gitfile)
                for line, vector_distance in lines:
                    result.add_line(line=line, vector_distance=vector_distance)
                results.append(result)

            del repository
            return results

        return mock_query

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
            "fetch": create_mock_query(repo, ripgrep_lines),
            "cache_chunk": noop,
            "cache_repo": noop,
        }
        mock_chroma.return_value = {
            "fetch": create_mock_query(repo, chroma_lines),
            "cache_chunk": noop,
            "cache_repo": noop,
        }
        yield


@pytest.fixture(name="create_prepared_seagoat")
def _create_prepared_seagoat(repo):
    def _prepared_seagoat(query, ripgrep_lines, chroma_lines):
        with mock_sources_context(repo, ripgrep_lines, chroma_lines):
            seagoat = Engine(repo.working_dir)
            seagoat.analyze_codebase()
            seagoat.query_sync(query)
            return seagoat

    return _prepared_seagoat


@pytest.fixture
def repo_with_more_files(repo):
    for i in range(250):
        repo.add_file_change_commit(
            file_name=f"file{i}.py",
            contents=("hello()\n" * (i % 50)),
            author=repo.actors["John Doe"],
            commit_message=f"add file{i}.py",
        )

    return repo


@pytest.fixture
def mock_sources(create_prepared_seagoat):
    ripgrep_lines = {
        "docs1.md": [(1, 15.0), (2, 6.0)],
        "docs2.md": [(1, 4.81)],
    }
    chroma_lines = {
        "docs2.md": [(2, 7.5)],
        "docs3.md": [(1, 5.332)],
    }
    my_query = "fake query"
    create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)


@pytest.fixture
def bat_not_available(mocker):
    """This fixture makes the assumption that bat is NOT available by default."""
    mocker.patch("seagoat.utils.cli_display.is_bat_installed", return_value=False)


@pytest.fixture(autouse=True)
def real_bat(bat_not_available):
    """This fixture sets the default behavior of is_bat_installed."""
    # Nothing to do here since bat_not_available has already set the behavior


@pytest.fixture
def bat_available(mocker):
    """This fixture makes bat available for tests that explicitly use it."""
    mocker.patch("seagoat.utils.cli_display.is_bat_installed", return_value=True)


@pytest.fixture
def bat_calls(mocker):
    calls = []

    def mock_bat(*args, **kwargs):
        if args[0] and args[0][0] == "bat":
            command_str = " ".join(args[0])
            calls.append(command_str)

            class MockResult:
                returncode = 0

            return MockResult()

        return ""

    mocker.patch("subprocess.run", side_effect=mock_bat)

    return calls


@pytest.fixture(autouse=True)
def mock_warn_if_update_available(mocker):
    return mocker.patch("seagoat.cli.warn_if_update_available")


@pytest.fixture
def create_config_file(repo):
    created_files = []

    def write_config(content, global_config=False):
        if global_config:
            config_file_path = GLOBAL_CONFIG_FILE
        else:
            config_file_path = Path(repo.working_dir) / ".seagoat.yml"

        os.makedirs(config_file_path.parent, exist_ok=True)

        with open(config_file_path, "w", encoding="utf-8") as file:
            yaml.dump(content, file)

        created_files.append(config_file_path)

    yield write_config

    for file_path in created_files:
        if file_path.exists():
            file_path.unlink()


@pytest.fixture
def temporary_cd():
    @contextmanager
    def _temporary_cd(path):
        old_dir = os.getcwd()
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(old_dir)

    return _temporary_cd


@pytest.fixture(scope="session")
def realistic_server(start_server):
    realrepo = tempfile.mkdtemp()
    subprocess.check_output(
        [
            "git",
            "clone",
            "https://github.com/kantord/i3-gnome-pomodoro.git",
            realrepo,
        ],
        text=True,
    )

    ## Checkout a specific commit to make sure the results are deterministic
    subprocess.check_output(
        [
            "git",
            "-C",
            realrepo,
            "checkout",
            "8bdea398906e7a706a28254cfd19b83dca136324",
        ],
        text=True,
    )

    subprocess.check_output(
        [
            "git",
            "-C",
            realrepo,
            "branch",
            "-D",
            "master",
        ],
        text=True,
    )

    subprocess.check_output(
        [
            "git",
            "-C",
            realrepo,
            "switch",
            "-c",
            "master",
        ],
        text=True,
    )
    my_engine = Engine(realrepo)
    my_engine.analyze_codebase(minimum_chunks_to_analyze=339)
    assert my_engine.cache.data["chunks_not_yet_analyzed"] == set()

    yield my_engine
    del my_engine

    shutil.rmtree(realrepo, ignore_errors=True)
