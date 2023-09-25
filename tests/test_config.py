from pathlib import Path

import pytest

from seagoat.utils.config import DEFAULT_CONFIG
from seagoat.utils.config import get_config
from seagoat.utils.config import GLOBAL_CONFIG_FILE


def test_no_config_files(repo):
    final_config = get_config(Path(repo.working_dir))
    assert final_config == DEFAULT_CONFIG


def write_config_file(file_path, content):
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)


@pytest.mark.parametrize(
    "config_content,expected_config",
    [
        ("server:\n  port: 6060", {"server": {"port": 6060}}),
        ("server:\n  port: 7070", {"server": {"port": 7070}}),
    ],
)
def test_local_config_override(repo, config_content, expected_config):
    GLOBAL_CONFIG_FILE.unlink(missing_ok=True)
    rc_file_path = Path(repo.working_dir) / ".seagoat.yml"
    write_config_file(rc_file_path, config_content)
    final_config = get_config(Path(repo.working_dir))
    assert final_config == expected_config
    rc_file_path.unlink()


@pytest.mark.parametrize(
    "global_config_content,expected_config",
    [
        ("server:\n  port: 6061", {"server": {"port": 6061}}),
        ("server:\n  port: 7072", {"server": {"port": 7072}}),
    ],
)
def test_global_config_override(repo, global_config_content, expected_config):
    write_config_file(GLOBAL_CONFIG_FILE, global_config_content)
    final_config = get_config(Path(repo.working_dir))
    assert final_config == expected_config
    GLOBAL_CONFIG_FILE.unlink()
