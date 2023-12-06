from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.errors import IDAlreadyExistsError
from chromadb.utils import embedding_functions

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.utils.config import get_config_values

MAXIMUM_VECTOR_DISTANCE = 1.5


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


def format_results(query_text: str, repository, chromadb_results):
    files = {}

    for metadata, distance in get_metadata_and_distance_from_chromadb_result(
        chromadb_results
    ):
        if distance > MAXIMUM_VECTOR_DISTANCE:
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

    def fetch(query_text: str, limit: int):
        # Slightly overfetch results as it will sorted using a different score later
        maximum_chunks_to_fetch = 100  # this should be plenty, especially because many times context could be included
        n_results = min((limit + 1) * 2, maximum_chunks_to_fetch)

        chromadb_results = chroma_collection.query(
            query_texts=[query_text],
            n_results=n_results,
        )

        return format_results(query_text, repository, chromadb_results)

    def cache_chunk(chunk):
        try:
            chroma_collection.add(
                ids=[chunk.chunk_id],
                documents=[chunk.chunk],
                metadatas=[
                    {
                        "path": chunk.path,
                        "line": chunk.codeline,
                        "git_object_id": chunk.object_id,
                    }
                ],
            )
        except IDAlreadyExistsError:
            pass

    def cache_repo():
        # chromadb does not need any repo cache action
        pass

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
        "cache_repo": cache_repo,
    }
