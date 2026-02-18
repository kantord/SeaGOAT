from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.utils.config import get_config_values


def get_metadata_and_distance_from_chromadb_result(chromadb_results):
    return (
        list(
            zip(
                chromadb_results["metadatas"][0],
                chromadb_results["distances"][0],
            )
        )
        if chromadb_results["metadatas"] and chromadb_results["distances"]
        else None
    ) or []


def format_results(query_text: str, repository, chromadb_results, config):
    files = {}
    max_vector_distance = config["server"]["chroma"]["maxVectorDistance"]

    for metadata, distance in get_metadata_and_distance_from_chromadb_result(
        chromadb_results
    ):
        if distance > max_vector_distance:
            break
        path = str(metadata["path"])
        line = int(metadata["line"])
        git_object_id = str(metadata["git_object_id"])
        full_path = Path(repository.path) / path

        if not full_path.exists():
            continue

        if not repository.is_up_to_date_git_object(path, git_object_id):
            continue

        gitfile = repository.get_file(path)

        if path not in files:
            files[path] = Result(query_text, gitfile)
        files[path].add_line(line, distance)

    return files.values()


def initialize(repository: Repository):
    cache = Cache("chroma", Path(repository.path), {})
    config = get_config_values(Path(repository.path))

    chroma_client = chromadb.PersistentClient(
        path=str(cache.get_cache_folder()),
        settings=Settings(
            anonymized_telemetry=False,
        ),
    )
    embedding_function_name = config["server"]["chroma"]["embeddingFunction"]["name"]
    embedding_function_kwargs = config["server"]["chroma"]["embeddingFunction"][
        "arguments"
    ]
    embedding_function = getattr(embedding_functions, embedding_function_name)(
        **embedding_function_kwargs
    )
    chroma_collection = chroma_client.get_or_create_collection(
        name="code_data", embedding_function=embedding_function
    )

    batch_size = config["server"]["chroma"]["batchSize"]
    batch_buffer = {"ids": [], "documents": [], "metadatas": []}

    def _flush_batch():
        if not batch_buffer["ids"]:
            return
        chroma_collection.upsert(
            ids=batch_buffer["ids"],
            documents=batch_buffer["documents"],
            metadatas=batch_buffer["metadatas"],
        )
        batch_buffer["ids"].clear()
        batch_buffer["documents"].clear()
        batch_buffer["metadatas"].clear()

    def fetch(query_text: str, limit: int):
        # Slightly overfetch results as it will sorted using a different score later
        max_chunks_to_fetch = config["server"]["chroma"]["maxChunksToFetch"]
        n_results_multiplier = config["server"]["chroma"]["nResultsMultiplier"]
        n_results = min((limit + 1) * n_results_multiplier, max_chunks_to_fetch)

        chromadb_results = chroma_collection.query(
            query_texts=[query_text],
            n_results=n_results,
        )

        return format_results(query_text, repository, chromadb_results, config)

    def cache_chunk(chunk):
        batch_buffer["ids"].append(chunk.chunk_id)
        batch_buffer["documents"].append(chunk.chunk)
        batch_buffer["metadatas"].append({
            "path": chunk.path,
            "line": chunk.codeline,
            "git_object_id": chunk.object_id,
        })
        if len(batch_buffer["ids"]) >= batch_size:
            _flush_batch()

    def cache_repo():
        # chromadb does not need any repo cache action
        pass

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
        "cache_repo": cache_repo,
        "flush_batch": _flush_batch,
    }
