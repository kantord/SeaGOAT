from pathlib import Path
from typing import Dict, List
import logging

import chromadb
from chromadb.config import Settings
from chromadb.errors import IDAlreadyExistsError
from chromadb.utils import embedding_functions

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.utils.config import get_config_values

MAXIMUM_VECTOR_DISTANCE = 1.5
DEFAULT_BATCH_SIZE = 1  # Default to no batching to maintain existing behavior
MAX_BATCH_SIZE = 250  # Maximum allowed batch size for safety

logger = logging.getLogger(__name__)


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


class BatchBuffer:
    """Manages batching of chunks for efficient ChromaDB operations"""
    
    def __init__(self, batch_size: int):
        self.batch_size = min(batch_size, MAX_BATCH_SIZE)  # Cap at max size
        self.ids: List[str] = []
        self.documents: List[str] = []
        self.metadatas: List[Dict] = []
        self._pending_count = 0
    
    def add(self, chunk_id: str, document: str, metadata: Dict) -> bool:
        """Add a chunk to the buffer. Returns True if buffer is full."""
        self.ids.append(chunk_id)
        self.documents.append(document)
        self.metadatas.append(metadata)
        self._pending_count += 1
        return self._pending_count >= self.batch_size
    
    def clear(self):
        """Clear the buffer"""
        self.ids.clear()
        self.documents.clear()
        self.metadatas.clear()
        self._pending_count = 0
    
    def is_empty(self) -> bool:
        """Check if buffer is empty"""
        return self._pending_count == 0
    
    def size(self) -> int:
        """Get current buffer size"""
        return self._pending_count


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

    # Get batch size from config with validation
    configured_batch_size = config["server"]["chroma"].get("batchSize", DEFAULT_BATCH_SIZE)
    if not isinstance(configured_batch_size, int) or configured_batch_size < 1:
        logger.warning(f"Invalid batchSize {configured_batch_size}, using default: {DEFAULT_BATCH_SIZE}")
        batch_size = DEFAULT_BATCH_SIZE
    else:
        batch_size = configured_batch_size
        if batch_size > MAX_BATCH_SIZE:
            logger.warning(f"batchSize {batch_size} exceeds maximum {MAX_BATCH_SIZE}, capping")
            batch_size = MAX_BATCH_SIZE
    
    # Initialize batch buffer
    batch_buffer = BatchBuffer(batch_size) if batch_size > 1 else None
    failed_chunks: List[Dict] = []  # Track failed chunks for retry

    def fetch(query_text: str, limit: int):
        # Slightly overfetch results as it will sorted using a different score later
        maximum_chunks_to_fetch = 100  # this should be plenty, especially because many times context could be included
        n_results = min((limit + 1) * 2, maximum_chunks_to_fetch)

        chromadb_results = chroma_collection.query(
            query_texts=[query_text],
            n_results=n_results,
        )

        return format_results(query_text, repository, chromadb_results)

    def _add_chunks_to_collection(ids: List[str], documents: List[str], metadatas: List[Dict]) -> List[int]:
        """
        Add chunks to collection with better error handling.
        Returns list of indices that failed to add.
        """
        failed_indices = []
        
        try:
            # Try to add all chunks at once
            chroma_collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
        except IDAlreadyExistsError as e:
            # If batch fails due to duplicate IDs, try individually
            logger.debug(f"Batch add failed with duplicate IDs, retrying individually: {e}")
            for i, (chunk_id, doc, meta) in enumerate(zip(ids, documents, metadatas)):
                try:
                    chroma_collection.add(
                        ids=[chunk_id],
                        documents=[doc],
                        metadatas=[meta],
                    )
                except IDAlreadyExistsError:
                    # This specific chunk already exists, skip it
                    logger.debug(f"Chunk {chunk_id} already exists, skipping")
                except Exception as e:
                    # Other error for this chunk
                    logger.error(f"Failed to add chunk {chunk_id}: {e}")
                    failed_indices.append(i)
        except Exception as e:
            # Other batch error - try to identify which chunks are problematic
            logger.error(f"Batch add failed: {e}")
            # Try each chunk individually to identify failures
            for i, (chunk_id, doc, meta) in enumerate(zip(ids, documents, metadatas)):
                try:
                    chroma_collection.add(
                        ids=[chunk_id],
                        documents=[doc],
                        metadatas=[meta],
                    )
                except Exception as e:
                    logger.debug(f"Failed to add chunk {chunk_id}: {e}")
                    failed_indices.append(i)
        
        return failed_indices

    def flush_batch():
        """Flush the current batch to ChromaDB with improved error handling"""
        if not batch_buffer or batch_buffer.is_empty():
            return
        
        # Get current batch data
        ids = batch_buffer.ids.copy()
        documents = batch_buffer.documents.copy()
        metadatas = batch_buffer.metadatas.copy()
        
        # Clear buffer immediately to avoid re-processing
        batch_buffer.clear()
        
        # Try to add chunks
        failed_indices = _add_chunks_to_collection(ids, documents, metadatas)
        
        # Store failed chunks for potential retry
        for idx in failed_indices:
            failed_chunks.append({
                'id': ids[idx],
                'document': documents[idx],
                'metadata': metadatas[idx]
            })
        
        if failed_indices:
            logger.warning(f"Failed to add {len(failed_indices)} chunks in batch")

    def cache_chunk(chunk):
        if not batch_buffer:
            # No batching - use original behavior with error handling
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
                logger.debug(f"Chunk {chunk.chunk_id} already exists")
            except Exception as e:
                logger.error(f"Failed to cache chunk {chunk.chunk_id}: {e}")
                failed_chunks.append({
                    'id': chunk.chunk_id,
                    'document': chunk.chunk,
                    'metadata': {
                        "path": chunk.path,
                        "line": chunk.codeline,
                        "git_object_id": chunk.object_id,
                    }
                })
        else:
            # Batching enabled
            should_flush = batch_buffer.add(
                chunk.chunk_id,
                chunk.chunk,
                {
                    "path": chunk.path,
                    "line": chunk.codeline,
                    "git_object_id": chunk.object_id,
                }
            )
            
            if should_flush:
                flush_batch()

    def cache_repo():
        """Called at the end of repository processing"""
        # Flush any remaining batched chunks
        if batch_buffer:
            flush_batch()
        
        # Log summary of any failed chunks
        if failed_chunks:
            logger.warning(f"Total {len(failed_chunks)} chunks failed to cache")
            # Optionally, we could retry failed chunks here with exponential backoff
            # For now, we just log them

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
        "cache_repo": cache_repo,
    }