import copy
import logging
import os
from pathlib import Path

import jsonschema
import yaml
from deepmerge import always_merger

from seagoat.utils.file_reader import read_file_with_correct_encoding
from seagoat.utils.paths import get_config_dir

DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",
        "port": None,
        "ignorePatterns": [],
        "readMaxCommits": 5_000,
        "chroma": {
            "batchSize": 20,
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
    "generative": {
        "provider": None,
        "model": None,
        "apiKey": None,
        "baseUrl": None,
        "temperature": None,
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
                "host": {"type": "string", "minLength": 1},
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
                        "batchSize": {"type": "integer", "minimum": 1},
                        "embeddingFunction": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "arguments": {"type": "object"},
                            },
                        },
                        "maxVectorDistance": {
                            "type": "number",
                            "minimum": 0.1,
                            "maximum": 10.0,
                        },
                        "maxChunksToFetch": {
                            "type": "integer",
                            "minimum": 10,
                            "maximum": 1000,
                        },
                        "nResultsMultiplier": {
                            "type": "number",
                            "minimum": 1.0,
                            "maximum": 10.0,
                        },
                    },
                },
                "ripgrep": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "maxFileSize": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10240,
                        },  # 1KB to 10MB
                        "maxMmapSize": {
                            "type": "integer",
                            "minimum": 10,
                            "maximum": 10000,
                        },  # 10MB to 10GB
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
                                "minValue": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 1000,
                                },
                                "percentage": {
                                    "type": "number",
                                    "minimum": 0.01,
                                    "maximum": 1.0,
                                },
                            },
                        },
                        "maxWorkers": {"type": "integer", "minimum": 1, "maximum": 32},
                    },
                },
                "query": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "defaultLimitClue": {
                            "type": "integer",
                            "minimum": 10,
                            "maximum": 10000,
                        },
                        "defaultContextAbove": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 50,
                        },
                        "defaultContextBelow": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 50,
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
        "generative": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["ollama", "openai", "minimax"],
                },
                "model": {"type": "string"},
                "apiKey": {"type": "string"},
                "baseUrl": {"type": "string"},
                "temperature": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
}

logger = logging.getLogger(__name__)

GLOBAL_CONFIG_DIR = get_config_dir()
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yml"

# server.engine.minChunksToAnalyze is deprecated and ignored. It stays in the
# schema so existing config files keep validating, and DEFAULT_CONFIG keeps the
# old defaults for library compatibility until the engine stops reading them,
# but an explicitly configured value is stripped from the parsed config file
# before any defaults are merged in. Detection happens on the parsed original
# config file, so an ordinary default configuration never triggers a warning.
_DEPRECATED_MIN_CHUNKS_TO_ANALYZE_KEY = ("server", "engine", "minChunksToAnalyze")
_warned_deprecated_min_chunks_files: set[Path] = set()


def _strip_deprecated_min_chunks_to_analyze(parsed_config: dict, config_file) -> None:
    """Drop the deprecated key from a parsed config file, warning once per file."""
    if _pop_key_path(parsed_config, _DEPRECATED_MIN_CHUNKS_TO_ANALYZE_KEY) is None:
        return
    config_file = Path(config_file)
    if config_file in _warned_deprecated_min_chunks_files:
        return
    _warned_deprecated_min_chunks_files.add(config_file)
    logger.warning(
        "Ignoring 'server.engine.minChunksToAnalyze' in %s: "
        "this setting is deprecated and ignored; it will be removed in a "
        "future version.",
        config_file,
    )


def validate_config_file(config_file: str):
    if os.path.exists(config_file):
        content = read_file_with_correct_encoding(config_file)
        new_config = yaml.safe_load(content) or {}
        jsonschema.validate(instance=new_config, schema=CONFIG_SCHEMA)
        return new_config
    return {}


def extend_config_with_file(base_config, config_file):
    new_config = validate_config_file(config_file)
    if new_config:
        _strip_deprecated_min_chunks_to_analyze(new_config, config_file)
    return always_merger.merge(base_config, new_config) if new_config else base_config


def get_global_config_values():
    config = copy.deepcopy(DEFAULT_CONFIG)

    if GLOBAL_CONFIG_FILE.exists():
        config = extend_config_with_file(config, GLOBAL_CONFIG_FILE)

    return config


def get_config_values(repo_path: Path):
    config = get_global_config_values()
    repo_config_file = repo_path / ".seagoat.yml"

    if repo_config_file.exists():
        repo_config = validate_config_file(str(repo_config_file))
        for key_path in GLOBAL_ONLY_KEYS:
            if _pop_key_path(repo_config, key_path) is not None:
                logger.warning(
                    "Ignoring '%s' in %s: set it in the global config file instead.",
                    ".".join(key_path),
                    repo_config_file,
                )
        _strip_deprecated_min_chunks_to_analyze(repo_config, repo_config_file)
        config = always_merger.merge(config, repo_config)

    return config


# The repo file is untrusted: it comes with whatever repository is being
# searched. These settings choose where code or credentials are sent or exposed,
# so only the global config file may set them.
GLOBAL_ONLY_KEYS = [
    # LLM provider and endpoint: would receive API keys and code
    ("generative",),
    # Any chroma embedding function with any arguments, e.g. an OpenAI one
    # with an attacker's api_base and api_key_env_var naming any environment
    # variable, which is then sent as a bearer token
    ("server", "chroma", "embeddingFunction"),
    # Network interface the server listens on: a repo must not be able to
    # expose your code to the network
    ("server", "host"),
    # One instance listens on one port for every project
    ("server", "port"),
    # Server the CLI sends queries to: it would receive every query, and
    # decide which file paths and text the CLI prints
    ("client", "host"),
]


def _pop_key_path(config: dict, key_path: tuple):
    *parents, key = key_path
    section = config
    for parent in parents:
        section = section.get(parent)
        if not isinstance(section, dict):
            return None
    return section.pop(key, None)
