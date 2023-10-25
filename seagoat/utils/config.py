import copy
import os
from pathlib import Path

import appdirs
import jsonschema
import yaml
from deepmerge import always_merger

from seagoat.utils.file_reader import read_file_with_correct_encoding

DEFAULT_CONFIG = {
    "server": {
        "port": None,
        "ignorePatterns": [],
        "chroma": {
            "embeddingFunction": {
                "name": "DefaultEmbeddingFunction",
                "arguments": {},
            },
        },
    },
    "client": {
        "host": None,
    },
}

CONFIG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "server": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "ignorePatterns": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "chroma": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "embeddingFunction": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "arguments": {"type": "object"},
                            },
                        },
                    },
                },
            },
        },
        "client": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "host": {"type": "string"},
            },
        },
    },
}

GLOBAL_CONFIG_DIR = Path(
    appdirs.user_config_dir(
        "seagoat-pytest" if "PYTEST_CURRENT_TEST" in os.environ else "seagoat"
    )
)
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yml"


def validate_config_file(config_file: str):
    if os.path.exists(config_file):
        content = read_file_with_correct_encoding(config_file)
        new_config = yaml.safe_load(content) or {}
        jsonschema.validate(instance=new_config, schema=CONFIG_SCHEMA)
        return new_config
    return {}


def extend_config_with_file(base_config, config_file):
    new_config = validate_config_file(config_file)
    return always_merger.merge(base_config, new_config) if new_config else base_config


def get_config_values(repo_path: Path):
    config = copy.deepcopy(DEFAULT_CONFIG)
    repo_config_file = repo_path / ".seagoat.yml"

    if GLOBAL_CONFIG_FILE.exists():
        config = extend_config_with_file(config, GLOBAL_CONFIG_FILE)

    if repo_config_file.exists():
        config = extend_config_with_file(config, repo_config_file)

    return config
