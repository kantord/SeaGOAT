from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.errors import IDAlreadyExistsError

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result


def initialize(repository: Repository):
    cache = Cache("chroma", Path(repository.path), {})

    chroma_client = chromadb.PersistentClient(
        path=str(cache.get_cache_folder()),
        settings=Settings(
            anonymized_telemetry=False,
        ),
    )

    chroma_collection = chroma_client.get_or_create_collection(name="code_data")

    def fetch(query_text: str, limit: int):
        # Slightly overfetch results as it will sorted using a different score later
        maximum_chunks_to_fetch = 100  # this should be plenty, especially because many times context could be included
        worst_distance_to_display = 1.5
        n_results = min((limit + 1) * 2, maximum_chunks_to_fetch)

        chromadb_results = [
            chroma_collection.query(
                query_texts=[query_text],
                n_results=n_results,
            )
        ]
        metadata_with_distance = (
            list(
                zip(
                    chromadb_results[0]["metadatas"][0],
                    chromadb_results[0]["distances"][0],
                )
            )
            if chromadb_results[0]["metadatas"] and chromadb_results[0]["distances"]
            else None
        ) or []

        files = {}

        for metadata, distance in metadata_with_distance:
            if distance > worst_distance_to_display:
                break
            path = str(metadata["path"])
            line = int(metadata["line"])

            if path not in files:
                files[path] = Result(path, Path(repository.path) / path)
            files[path].add_line(line, distance)

        return files.values()

    def cache_chunk(chunk):
        try:
            chroma_collection.add(
                ids=[chunk.chunk_id],
                documents=[chunk.chunk],
                metadatas=[{"path": chunk.path, "line": chunk.codeline}],
            )
        except IDAlreadyExistsError:
            pass

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
    }
