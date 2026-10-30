import copy
import logging
import os
import tempfile
from pathlib import Path

import jsonschema
import platformdirs
import yaml
from deepmerge import always_merger

from seagoat.utils.file_reader import read_file_with_correct_encoding
from seagoat.utils.server import normalize_repo_path

DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",
        "port": None,
        "repositories": [],
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
                "repositories": {
                    "type": "array",
                    "items": {"type": "string"},
                },
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

GLOBAL_CONFIG_DIR = Path(
    platformdirs.user_config_dir(
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
        config = always_merger.merge(config, repo_config)

    return config


def add_repository(repo_path) -> bool:
    # Imported here because seagoat.projects imports seagoat.utils.config
    from seagoat.projects import resolve_repo_path

    config = {}
    if GLOBAL_CONFIG_FILE.exists():
        config = validate_config_file(str(GLOBAL_CONFIG_FILE)) or {}

    repositories = config.setdefault("server", {}).setdefault("repositories", [])
    normalized_path = normalize_repo_path(resolve_repo_path(repo_path))

    if any(normalize_repo_path(path) == normalized_path for path in repositories):
        return False

    repositories.append(normalized_path)
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Write through a temporary file and os.replace so a concurrent reader
    # never sees a half-written config file.
    fd, temp_path = tempfile.mkstemp(
        dir=GLOBAL_CONFIG_DIR, prefix=".config-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as config_file:
            yaml.safe_dump(config, config_file, sort_keys=False)
        os.replace(temp_path, GLOBAL_CONFIG_FILE)
    finally:
        Path(temp_path).unlink(missing_ok=True)
    return True


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
    # Which repositories an instance serves is the instance owner's choice, never a repository's
    ("server", "repositories"),
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
