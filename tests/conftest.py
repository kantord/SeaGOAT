import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Give this pytest session its own cache and config directories, so two runs
# (for example in two worktrees) never share the instance file,
# repositories.json or the global config. Must be set before seagoat is
# imported: seagoat.utils.config reads the config directory at module load
# time and seagoat.utils.server reads the cache directory per request.
# SEAGOAT_CACHE_DIR/SEAGOAT_CONFIG_DIR work on every platform (platformdirs
# ignores XDG_* on macOS and Windows); the XDG_* lines are kept too for tools
# that read them.
SESSION_TEMP_DIR = Path(tempfile.mkdtemp(prefix="seagoat-pytest-"))
os.environ["SEAGOAT_CACHE_DIR"] = str(SESSION_TEMP_DIR / "cache")
os.environ["SEAGOAT_CONFIG_DIR"] = str(SESSION_TEMP_DIR / "config")
os.environ["XDG_CACHE_HOME"] = str(SESSION_TEMP_DIR / "cache")
os.environ["XDG_CONFIG_HOME"] = str(SESSION_TEMP_DIR / "config")

# Server subprocesses started by tests log embedding-cache misses here; the
# option --update-embedding-cache turns them into the committed cache file.
# Must be set before seagoat is imported (the fixture reads it at call time,
# but keep it next to the other per-session paths).
EMBEDDING_MISSES_LOG_DIR = SESSION_TEMP_DIR / "embedding-misses"
os.environ["SEAGOAT_EMBEDDING_CACHE_LOG"] = str(EMBEDDING_MISSES_LOG_DIR)
EMBEDDING_MISSES_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Guard the test suite's processes against the outside world.

# Network: allow only localhost plus the embedding model download host. Nothing
# listens on 127.0.0.1:9, so requests/httpx fail fast, in-process and in every
# subprocess. The ONNX model host must stay reachable: on a fresh machine or CI
# chromadb downloads the model from
# https://chroma-onnx-models.s3.amazonaws.com/... into ~/.cache/chroma.
_proxy = "http://127.0.0.1:9"
_no_proxy = "localhost,127.0.0.1,::1,chroma-onnx-models.s3.amazonaws.com"
for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ[_proxy_var] = _proxy
for _no_proxy_var in ("NO_PROXY", "no_proxy"):
    os.environ[_no_proxy_var] = _no_proxy

# Secrets: tests that need a credential set it themselves (mocker.patch.dict /
# monkeypatch); nothing here may leak a real one into server subprocesses.
for _secret_var in [
    _name
    for _name in os.environ
    if _name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
    or _name.startswith("AWS_")
]:
    del os.environ[_secret_var]

import copy
import json
from collections import defaultdict
from contextlib import contextmanager
from typing import cast
from unittest.mock import MagicMock

import numpy as np
import orjson
import pytest
import yaml
from click.testing import CliRunner
from deepmerge import always_merger

from seagoat.cache import get_cache_root
from seagoat.engine import Engine
from seagoat.projects import Projects
from seagoat.server import create_app
from seagoat.utils.config import GLOBAL_CONFIG_FILE
from seagoat.utils.server import (
    Instance,
    instance_url,
    read_instance,
    running_instance,
)
from seagoat.utils.wait import wait_for
from tests.fixtures.mock_repo import MockRepo
from tests.fixtures.realistic_repo import build
from tests.fixtures.sources import mock_sources_context
from tests.process_guard import set_pdeathsig

try:
    from pytest_cov.embed import cleanup_on_sigterm
except ImportError:
    pass
else:
    cleanup_on_sigterm()


@pytest.fixture(scope="session", autouse=True)
def suppress_chromadb_logger():
    logging.getLogger("chromadb").setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def repo_template():
    # Build the fake repo once per session, then copy it for every test that
    # needs a repo. This avoids paying the cost of 12 GitPython commits ~270
    # times. The template's fake_commit_date is remembered AFTER add_fake_data
    # because it was ticked forward per commit; every copy must keep producing
    # commits after the template's commits, exactly as before.
    #
    # The template's commit dates are anchored at "now - 400 days", computed
    # when the session builds the template (what MockRepo did before the
    # template existed). The youngest fake commit is therefore exactly 389 days
    # old on the day the session runs, so frecency-based rankings no longer
    # drift as real time passes. Tests that fake the clock with freezegun
    # (e.g. test_repository.py::test_file_score_is_recalculated_when_needed,
    # which freezes "today" to 2012-01-14/2018-01-15) cannot use template
    # copies: those commits would lie in the future relative to the frozen
    # "today". They must build a fresh repo with ``generate_fresh_repo``, whose
    # commits are anchored at the frozen "now" instead. All copies share the
    # same anchored dates, so every frecency-based ranking inside a test is
    # exactly the same as with per-test repos.
    template_dir = tempfile.mkdtemp()
    template_repo = cast(MockRepo, MockRepo.init(template_dir))
    template_repo.fake_commit_date = datetime.now(UTC) - timedelta(days=400)
    template_repo.add_fake_data()
    fake_commit_date = template_repo.fake_commit_date
    template_repo.close()

    yield template_dir, fake_commit_date

    shutil.rmtree(template_dir, ignore_errors=True)


@pytest.fixture
def generate_repo(repo_template):
    template_dir, fake_commit_date = repo_template
    directories_to_delete = []
    repos_to_delete = []

    def repo_generator():
        new_directory = tempfile.mkdtemp()
        directories_to_delete.append(new_directory)
        shutil.copytree(template_dir, new_directory, symlinks=True, dirs_exist_ok=True)
        repo = cast(MockRepo, MockRepo(new_directory))
        # MockRepo.__init__ resets fake_commit_date to now-400 days; restore the
        # template's final date so later test commits come after the template's.
        repo.fake_commit_date = fake_commit_date
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
def generate_fresh_repo():
    """Build a brand new MockRepo (with fake data) only when called.

    Unlike ``generate_repo``, the repo is created *inside* the caller's
    (possibly frozen) clock, so tests that use freezegun get commits anchored
    at the frozen "now" instead of the session's template dates.
    """
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
    return generate_repo()


_kept_cache_folders: set[Path] = set()


def keep_cache_folder(path: Path) -> None:
    """Register a cache folder so per-test cleanup keeps it (session fixtures)."""
    _kept_cache_folders.add(Path(path).resolve())


def _delete_unkept_cache_entries(cache_root: Path) -> None:
    """Delete every entry in the cache folder except registered kept folders."""
    if not cache_root.is_dir():
        return

    for entry in cache_root.iterdir():
        if entry.resolve() in _kept_cache_folders:
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


# Every test session uses the cached embedding function unless a test opts
# out with the `real_embeddings` marker. Test-specific global configs written
# with create_config_file(global_config=True) are deep-merged over this.
BASELINE_GLOBAL_CONFIG = {
    "server": {
        "chroma": {
            "embeddingFunction": {
                "name": "tests.fixtures.embedding_cache:CachedEmbeddingFunction",
                "arguments": {},
            }
        }
    }
}


def _write_global_config(content: dict) -> None:
    GLOBAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GLOBAL_CONFIG_FILE, "w", encoding="utf-8") as file:
        yaml.dump(content, file)


def _write_baseline_global_config(baseline: dict) -> None:
    if baseline:
        _write_global_config(copy.deepcopy(baseline))
    else:
        GLOBAL_CONFIG_FILE.unlink(missing_ok=True)


@pytest.fixture
def global_config_baseline(request) -> dict:
    """The global config a test starts from.

    BASELINE_GLOBAL_CONFIG (cached embeddings), or none at all (seagoat's
    defaults, so the real ONNX model) for tests marked real_embeddings: the
    real-model smoke test, and tests that compare against seagoat's default
    configuration. create_config_file(global_config=True) merges over it.
    """
    if request.node.get_closest_marker("real_embeddings") is not None:
        return {}
    return BASELINE_GLOBAL_CONFIG


def _clean_instance_state(baseline: dict = BASELINE_GLOBAL_CONFIG) -> None:
    # Each test starts from a clean slate: no instance, no repositories file
    # and only the baseline global config (start commands add repositories
    # while tests run).
    from seagoat.utils.server import instance_file_path, repositories_file_path

    instance_path = instance_file_path()
    for file_path in (
        instance_path,
        repositories_file_path(),
        Path(f"{instance_path}.lock"),
    ):
        file_path.unlink(missing_ok=True)
    _write_baseline_global_config(baseline)


@pytest.fixture(autouse=True)
def run_around_tests(global_config_baseline):
    _clean_instance_state(global_config_baseline)
    yield
    _delete_unkept_cache_entries(get_cache_root())
    _clean_instance_state()


def _server_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "seagoat.server", *args]


@pytest.fixture
def start_seagoat_server(managed_process):
    """Start `seagoat-server start ARGS` as a child process and wait for it."""

    @contextmanager
    def _start(*args: str):
        # Send the server's output to a file: a pipe could fill up and deadlock
        # the server while tests are not reading it
        with (
            tempfile.TemporaryDirectory() as output_dir,
            (Path(output_dir) / "server_output.log").open("wb") as server_output,
            managed_process(
                _server_command("start", *args),
                stdout=server_output,
                stderr=subprocess.STDOUT,
            ) as process,
        ):
            process.output_file = Path(server_output.name)
            wait_for(lambda: running_instance() is not None, 8)
            instance = read_instance()
            assert instance is not None
            yield process, instance

    return _start


@pytest.fixture(name="server")
def _server(repo, start_seagoat_server):
    with start_seagoat_server(str(repo.working_dir)) as (_, instance):
        yield instance_url(instance)


@pytest.fixture
def init_server_mock(mocker):
    def _init_server_mock():
        instance = Instance(host="localhost", port=1234, pid=1)
        mocker.patch(
            "seagoat.cli.running_instance",
            return_value=(instance, {"pid": instance.pid, "projects": []}),
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
                        "resultTypes": ["context"] if is_context_line else ["result"],
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
def runner(mock_spinner):
    return CustomCliRunner()


@pytest.fixture
def mock_spinner(mocker):
    mocker.patch("seagoat.cli.yaspin")

    yield


@pytest.fixture
def runner_with_error(mocker, mock_spinner):
    # click >= 8.2 always keeps stdout and stderr separate
    return CliRunner()


@pytest.fixture
def client(repo):
    mock_queue = MagicMock()

    projects = Projects(lambda path, config: mock_queue)
    projects.get(repo.working_dir)
    app = create_app(projects, "127.0.0.1")
    app.config["TESTING"] = True
    client = app.test_client()

    client._mock_queue = mock_queue  # type: ignore

    yield client


@pytest.fixture
def mock_queue(client):
    yield client._mock_queue


@pytest.fixture
def managed_process():
    processes = []

    def _kill_group(proc):
        """SIGTERM the whole process group, wait 10s, then SIGKILL it."""
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()

    @contextmanager
    def _process(*args, **kwargs):
        # Own session so the whole process group dies together; on Linux the
        # child also asks the kernel to SIGTERM it if pytest is SIGKILLed.
        kwargs.setdefault("start_new_session", True)
        if sys.platform == "linux":
            kwargs.setdefault("preexec_fn", set_pdeathsig)
        proc = subprocess.Popen(*args, **kwargs)
        processes.append(proc)
        try:
            yield proc
        finally:
            _kill_group(proc)
            processes.remove(proc)

    yield _process

    for proc in processes:
        _kill_group(proc)


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
            commit_message=f"add file{i}.py",
        )

    return repo


@pytest.fixture(autouse=True)
def assume_bat_not_installed(request, mocker):
    """Tests run as if bat is not installed, unless marked real_bat_check."""
    if request.node.get_closest_marker("real_bat_check"):
        return
    mocker.patch("seagoat.utils.cli_display.is_bat_installed", return_value=False)


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
def create_config_file(repo, global_config_baseline):
    created_files = []

    def write_config(content, global_config=False):
        if global_config:
            config_file_path = GLOBAL_CONFIG_FILE
            # Keep the cached embedding function from the baseline unless the
            # test explicitly overrides it.
            merged = copy.deepcopy(global_config_baseline)
            always_merger.merge(merged, content)
            content = merged
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
def create_repositories_file():
    created_files = []

    def write_repositories(repositories):
        from seagoat.utils.json_file import write_to_json_file
        from seagoat.utils.server import repositories_file_path

        file_path = repositories_file_path()
        write_to_json_file(file_path, repositories)
        created_files.append(file_path)

    yield write_repositories

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
def realistic_engine():
    # A made-up repository the suite builds itself, so no test needs the network
    realrepo = tempfile.mkdtemp()
    build(realrepo)

    my_engine = Engine(realrepo)
    keep_cache_folder(my_engine.cache.get_cache_folder())
    my_engine.analyze_codebase(minimum_chunks_to_analyze=351)
    assert my_engine.cache.data["chunks_not_yet_analyzed"] == set()

    yield my_engine
    del my_engine

    shutil.rmtree(realrepo, ignore_errors=True)


def pytest_addoption(parser):
    parser.addoption(
        "--update-embedding-cache",
        action="store_true",
        default=False,
        help="Add embeddings missed during the run to tests/fixtures/embedding_cache.npz",
    )


def _collect_embedding_misses() -> dict:
    misses = {}
    if not EMBEDDING_MISSES_LOG_DIR.is_dir():
        return misses
    for log_file in EMBEDDING_MISSES_LOG_DIR.glob("*.jsonl"):
        with open(log_file, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                key, vector = json.loads(line)
                misses[key] = vector
    return misses


def _update_embedding_cache_file(misses: dict) -> None:
    from tests.fixtures.embedding_cache import _CACHE_FILE

    if not misses:
        return
    existing = {}
    if _CACHE_FILE.exists():
        data = np.load(_CACHE_FILE)
        for key, vector in zip(data["keys"], data["vectors"]):
            existing[str(key)] = np.asarray(vector, dtype=np.float32)
    for key, vector in misses.items():
        existing[key] = np.asarray(vector, dtype=np.float32)
    all_keys = sorted(existing.keys())
    all_vectors = np.stack([existing[key] for key in all_keys])
    np.savez(_CACHE_FILE, keys=np.array(all_keys), vectors=all_vectors)


def pytest_sessionfinish(session, exitstatus):
    misses = _collect_embedding_misses()
    if session.config.getoption("--update-embedding-cache"):
        _update_embedding_cache_file(misses)
    else:
        session.config._embedding_miss_count = len(misses)
    # Remove the per-session cache/config directory here rather than in a
    # session-scoped fixture: pytest tears session fixtures down during the
    # last test, i.e. before pytest_sessionfinish runs, and the embedding
    # misses log (SESSION_TEMP_DIR/embedding-misses) must survive until then.
    shutil.rmtree(SESSION_TEMP_DIR, ignore_errors=True)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    miss_count = getattr(config, "_embedding_miss_count", 0)
    if miss_count:
        terminalreporter.write_sep(
            "-",
            f"{miss_count} embeddings missing from tests/fixtures/embedding_cache.npz; "
            "rerun with --update-embedding-cache",
        )
