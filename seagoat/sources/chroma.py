from pathlib import Path

from chromadb import chromadb
from chromadb.errors import IDAlreadyExistsError

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result


def initialize(repository: Repository):
    cache = Cache("chroma", Path(repository.path), {})
    chroma_client = chromadb.Client(
        chromadb.Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=str(cache.get_cache_folder()),
            anonymized_telemetry=False,
        )
    )
    chroma_collection = chroma_client.get_or_create_collection(name="code_data")

    def fetch(query_text: str):
        chromadb_results = [
            chroma_collection.query(query_texts=[query_text], n_results=50)
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
        "persist": chroma_client.persist,
    }
