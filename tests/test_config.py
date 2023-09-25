from pathlib import Path

import pytest

from seagoat.utils.config import DEFAULT_CONFIG
from seagoat.utils.config import get_config


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
    rc_file_path = Path(repo.working_dir) / ".seagoat.yml"
    write_config_file(rc_file_path, config_content)
    final_config = get_config(Path(repo.working_dir))
    assert final_config == expected_config
    rc_file_path.unlink()
