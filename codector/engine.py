"""
    This module allows you to use Codector as a library
"""

from pathlib import Path
import hashlib

from git.repo import Repo
from tqdm import tqdm
from gitdb.db.loose import os
import appdirs
import chromadb
from chromadb.errors import IDAlreadyExistsError

from codector.repository import Repository
from codector.result import Result

CACHE_FORMAT_VERSION = 12


class Engine:
    """
    A search engine for a code repository
    """

    def __init__(self, path: str):
        """
        Initializes the library
        """
        self.path = path
        self._repo = Repo(path)
        self.query_string = ""
        self._results = []
        self._chroma_client = chromadb.Client()
        self._chroma_collection = self._chroma_client.create_collection(
            name="code_data"
        )
        self.repository = Repository(path, self._get_cache_folder())

    def _get_cache_folder(self):
        cache_folder = self._get_cache_root() / self._get_project_hash()
        cache_folder.mkdir(parents=True, exist_ok=True)

        return cache_folder

    def _get_cache_root(self):
        return Path(
            appdirs.user_cache_dir(
                "codector-pytest" if "PYTEST_CURRENT_TEST" in os.environ else "codector"
            )
        )

    def _get_project_hash(self):
        normalized_path = Path(self.path).expanduser().resolve()
        text = f"""
        Cache version: {CACHE_FORMAT_VERSION}
        Normalized path: {normalized_path}
        """

        return hashlib.sha256(text.encode()).hexdigest()

    def analyze_codebase(self):
        self.repository.analyze_files()
        self._create_vector_embeddings()

    def _create_vector_embeddings(self):
        chunks_to_process = []
        for file in self.repository.top_files()[:24]:
            for chunk in file.get_chunks():
                chunks_to_process.append(chunk)

        for chunk in tqdm(chunks_to_process, desc="Training AI"):
            try:
                self._chroma_collection.add(
                    ids=[chunk.chunk_id],
                    documents=[chunk.chunk],
                    metadatas=[{"path": chunk.path, "line": chunk.codeline}],
                )
            except IDAlreadyExistsError:
                pass

    def query(self, query: str):
        self.query_string = query

    def fetch(self):
        chromadb_results = [
            self._chroma_collection.query(query_texts=[self.query_string], n_results=5)
        ]
        metadatas = (
            chromadb_results[0]["metadatas"][0]
            if chromadb_results[0]["metadatas"]
            else None
        )

        self._results = [str(item["path"]) for item in metadatas] if metadatas else []

    def get_results(self):
        return [Result(path) for path in self._results]
