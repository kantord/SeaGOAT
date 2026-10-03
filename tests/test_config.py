from pathlib import Path

import jsonschema
import pytest
from deepmerge import always_merger

from seagoat.utils.config import (
    DEFAULT_CONFIG,
    GLOBAL_CONFIG_FILE,
    get_config_values,
)


def _(config):
    return always_merger.merge({**DEFAULT_CONFIG}, {**config})


def test_no_config_files(repo):
    final_config = get_config_values(Path(repo.working_dir))
    assert final_config == DEFAULT_CONFIG


@pytest.mark.parametrize(
    "config_content,expected_port",
    [
        ({"server": {"port": 6060}}, 6060),
        ({"server": {"port": 7070}}, 7070),
    ],
)
def test_local_config_override(repo, config_content, expected_port, create_config_file):
    GLOBAL_CONFIG_FILE.unlink(missing_ok=True)
    create_config_file(config_content, global_config=False)
    final_config = get_config_values(Path(repo.working_dir))
    assert final_config["server"]["port"] == expected_port


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
            {"server": {"port": 6060}},
            {"server": {"port": 7070}},
            {"server": {"port": 7070}},
        ),
        (
            {"server": {"port": 8000}},
            {"server": {"port": 9000}},
            {"server": {"port": 9000}},
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
