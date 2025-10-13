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
        "readMaxCommits": 5_000,
        "chroma": {
            "embeddingFunction": {
                "name": "DefaultEmbeddingFunction",
                "arguments": {},
            },
            "maxVectorDistance": 1.5,
            "maxChunksToFetch": 100,
            "nResultsMultiplier": 2,
        },
        "ripgrep": {
            "maxFileSize": 200,  # 200 KB
            "maxMmapSize": 500,  # 500 MB
        },
        "engine": {
            "minChunksToAnalyze": {
                "minValue": 40,
                "percentage": 0.2,
            },
            "maxWorkers": 1,
        },
        "query": {
            "defaultLimitClue": 500,
            "defaultContextAbove": 3,
            "defaultContextBelow": 3,
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
                "readMaxCommits": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "maximum": 65535,
                },
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
                        "maxVectorDistance": {"type": "number", "minimum": 0.1, "maximum": 10.0},
                        "maxChunksToFetch": {"type": "integer", "minimum": 10, "maximum": 1000},
                        "nResultsMultiplier": {"type": "number", "minimum": 1.0, "maximum": 10.0},
                    },
                },
                "ripgrep": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "maxFileSize": {"type": "integer", "minimum": 1, "maximum": 10240},  # 1KB to 10MB
                        "maxMmapSize": {"type": "integer", "minimum": 10, "maximum": 10000},  # 10MB to 10GB
                    },
                },
                "engine": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "minChunksToAnalyze": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "minValue": {"type": "integer", "minimum": 1, "maximum": 1000},
                                "percentage": {"type": "number", "minimum": 0.01, "maximum": 1.0},
                            },
                        },
                        "maxWorkers": {"type": "integer", "minimum": 1, "maximum": 32},
                    },
                },
                "query": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "defaultLimitClue": {"type": "integer", "minimum": 10, "maximum": 10000},
                        "defaultContextAbove": {"type": "integer", "minimum": 0, "maximum": 50},
                        "defaultContextBelow": {"type": "integer", "minimum": 0, "maximum": 50},
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
