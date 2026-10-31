import copy
from pathlib import Path

import jsonschema
import pytest
from deepmerge import always_merger

from seagoat.utils.config import (
    DEFAULT_CONFIG,
    GLOBAL_CONFIG_FILE,
    get_config_values,
    get_global_config_values,
)

# These tests compare against seagoat's default configuration, so they must
# not start from the test suite's cached-embeddings global config.
pytestmark = pytest.mark.real_embeddings


def _(config):
    # The merge mutates its first argument, so give it a private copy
    # instead of the shared DEFAULT_CONFIG.
    return always_merger.merge(copy.deepcopy(DEFAULT_CONFIG), config)


def test_no_config_files(repo):
    final_config = get_config_values(Path(repo.working_dir))
    assert final_config == DEFAULT_CONFIG


@pytest.mark.parametrize(
    "config_content,expected_read_max_commits",
    [
        ({"server": {"readMaxCommits": 6060}}, 6060),
        ({"server": {"readMaxCommits": 7070}}, 7070),
    ],
)
def test_local_config_override(
    repo, config_content, expected_read_max_commits, create_config_file
):
    GLOBAL_CONFIG_FILE.unlink(missing_ok=True)
    create_config_file(config_content, global_config=False)
    final_config = get_config_values(Path(repo.working_dir))
    assert final_config["server"]["readMaxCommits"] == expected_read_max_commits


@pytest.mark.parametrize(
    "global_config_content,expected_port",
    [
        ({"server": {"port": 6061}}, 6061),
        ({"server": {"port": 7072}}, 7072),
    ],
)
def test_global_config_override(
    repo, global_config_content, expected_port, create_config_file
):
    create_config_file(global_config_content, global_config=True)
    final_config = get_config_values(Path(repo.working_dir))
    assert final_config["server"]["port"] == expected_port


@pytest.mark.parametrize(
    "global_config_content,local_config_content,expected_config",
    [
        (
            {"server": {"readMaxCommits": 6060}},
            {"server": {"readMaxCommits": 7070}},
            {"server": {"readMaxCommits": 7070}},
        ),
        (
            {"server": {"readMaxCommits": 8000}},
            {"server": {"readMaxCommits": 9000}},
            {"server": {"readMaxCommits": 9000}},
        ),
    ],
)
def test_local_overrides_global(
    repo,
    global_config_content,
    local_config_content,
    expected_config,
    create_config_file,
):
    create_config_file(global_config_content, global_config=True)
    create_config_file(local_config_content, global_config=False)

    final_config = get_config_values(Path(repo.working_dir))
    assert final_config == _(expected_config)


def test_repo_config_port_is_ignored_uses_global(repo, create_config_file, caplog):
    create_config_file({"server": {"port": 6060}}, global_config=True)
    create_config_file({"server": {"port": 7070}}, global_config=False)

    config = get_config_values(Path(repo.working_dir))

    assert config["server"]["port"] == 6060
    assert "Ignoring 'server.port'" in caplog.text


@pytest.mark.parametrize(
    "invalid_config_content",
    [
        ({"server": {"port": "invalid_port"}}),
        ({"foobar": {"asdf": None}}),
    ],
)
def test_invalid_config_throws_exception(
    repo, invalid_config_content, create_config_file
):
    create_config_file(invalid_config_content, global_config=False)  # or True if needed

    with pytest.raises(jsonschema.exceptions.ValidationError):  # type: ignore
        get_config_values(Path(repo.working_dir))


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("chroma", "maxVectorDistance", 0),
        ("chroma", "maxChunksToFetch", 5),
        ("chroma", "nResultsMultiplier", 0.5),
        ("ripgrep", "maxFileSize", 0),
        ("ripgrep", "maxMmapSize", 5),
        ("engine", "maxWorkers", 0),
        ("engine", "maxWorkers", 33),
        ("query", "defaultLimitClue", 1),
        ("query", "defaultContextAbove", -1),
    ],
)
def test_rejects_out_of_range_values(repo, section, key, value, create_config_file):
    create_config_file({"server": {section: {key: value}}}, global_config=False)

    with pytest.raises(jsonschema.ValidationError):
        get_config_values(Path(repo.working_dir))


def test_rejects_zero_min_chunks_to_analyze(repo, create_config_file):
    create_config_file(
        {"server": {"engine": {"minChunksToAnalyze": {"minValue": 0}}}},
        global_config=False,
    )

    with pytest.raises(jsonschema.ValidationError):
        get_config_values(Path(repo.working_dir))


def test_accepts_fractional_n_results_multiplier(repo, create_config_file):
    create_config_file(
        {"server": {"chroma": {"nResultsMultiplier": 2.5}}}, global_config=False
    )

    config = get_config_values(Path(repo.working_dir))

    assert config["server"]["chroma"]["nResultsMultiplier"] == 2.5


@pytest.mark.parametrize(
    "repo_config,key_path",
    [
        (
            {
                "server": {
                    "chroma": {
                        "embeddingFunction": {
                            "name": "OpenAIEmbeddingFunction",
                            "arguments": {
                                "api_base": "https://evil.example/v1",
                                "api_key_env_var": "GITHUB_TOKEN",
                            },
                        }
                    }
                }
            },
            ("server", "chroma", "embeddingFunction"),
        ),
        ({"server": {"host": "0.0.0.0"}}, ("server", "host")),  # nosec B104 - config only
        ({"client": {"host": "https://evil.example/"}}, ("client", "host")),
    ],
)
def test_repo_config_cannot_set_global_only_keys(
    repo, repo_config, key_path, create_config_file, caplog
):
    create_config_file(repo_config, global_config=False)

    config = get_config_values(Path(repo.working_dir))

    expected = DEFAULT_CONFIG
    actual = config
    for key in key_path:
        expected = expected[key]
        actual = actual[key]
    assert actual == expected
    assert f"Ignoring '{'.'.join(key_path)}'" in caplog.text


def test_repo_config_keeps_other_chroma_settings(repo, create_config_file):
    create_config_file(
        {
            "server": {
                "chroma": {
                    "batchSize": 7,
                    "embeddingFunction": {"name": "OpenAIEmbeddingFunction"},
                }
            }
        },
        global_config=False,
    )

    config = get_config_values(Path(repo.working_dir))

    assert config["server"]["chroma"]["batchSize"] == 7
    assert config["server"]["chroma"]["embeddingFunction"]["name"] == (
        "DefaultEmbeddingFunction"
    )


def test_global_config_can_set_embedding_function(repo, create_config_file):
    create_config_file(
        {"server": {"chroma": {"embeddingFunction": {"name": "Custom"}}}},
        global_config=True,
    )

    config = get_config_values(Path(repo.working_dir))

    assert config["server"]["chroma"]["embeddingFunction"]["name"] == "Custom"


def test_server_listens_on_localhost_by_default(repo):
    config = get_config_values(Path(repo.working_dir))

    assert config["server"]["host"] == "127.0.0.1"


def test_global_config_can_set_server_host(repo, create_config_file):
    create_config_file({"server": {"host": "0.0.0.0"}}, global_config=True)  # nosec B104

    config = get_config_values(Path(repo.working_dir))

    assert config["server"]["host"] == "0.0.0.0"  # nosec B104 - config only


def test_config_defaults_have_no_repositories(repo):
    config = get_config_values(Path(repo.working_dir))

    assert "repositories" not in DEFAULT_CONFIG["server"]
    assert "repositories" not in config["server"]


def test_global_config_with_repositories_is_invalid(repo, create_config_file):
    create_config_file(
        {"server": {"repositories": ["/repo/one", "/repo/two"]}},
        global_config=True,
    )

    with pytest.raises(jsonschema.ValidationError):
        get_config_values(Path(repo.working_dir))


def test_get_global_config_values_ignores_repo_config(repo, create_config_file):

    create_config_file({"server": {"readMaxCommits": 7070}}, global_config=False)

    config = get_global_config_values()

    assert (
        config["server"]["readMaxCommits"] == DEFAULT_CONFIG["server"]["readMaxCommits"]
    )


def test_get_global_config_values_reads_global_config(repo, create_config_file):

    create_config_file({"server": {"port": 6061}}, global_config=True)

    config = get_global_config_values()

    assert config["server"]["port"] == 6061
