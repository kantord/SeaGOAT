from pathlib import Path

import pytest

from seagoat.utils.config import DEFAULT_CONFIG
from seagoat.utils.config import get_config
from seagoat.utils.config import GLOBAL_CONFIG_FILE


base_expected_config = {**DEFAULT_CONFIG}


def _(config):
    return {**base_expected_config, **config}


def test_no_config_files(repo):
    final_config = get_config(Path(repo.working_dir))
    assert final_config == DEFAULT_CONFIG


@pytest.mark.parametrize(
    "config_content,expected_config",
    [
        ({"server": {"port": 6060}}, _({"server": {"port": 6060}})),
        ({"server": {"port": 7070}}, _({"server": {"port": 7070}})),
    ],
)
def test_local_config_override(
    repo, config_content, expected_config, create_config_file
):
    GLOBAL_CONFIG_FILE.unlink(missing_ok=True)
    create_config_file(config_content, global_config=False)
    final_config = get_config(Path(repo.working_dir))
    assert final_config == expected_config


@pytest.mark.parametrize(
    "global_config_content,expected_config",
    [
        ({"server": {"port": 6061}}, _({"server": {"port": 6061}})),
        ({"server": {"port": 7072}}, _({"server": {"port": 7072}})),
    ],
)
def test_global_config_override(
    repo, global_config_content, expected_config, create_config_file
):
    create_config_file(global_config_content, global_config=True)
    final_config = get_config(Path(repo.working_dir))
    assert final_config == expected_config


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

    final_config = get_config(Path(repo.working_dir))
    assert final_config == _(expected_config)
