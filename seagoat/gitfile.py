import functools

from seagoat import _native


# Keyed by git object, not by GitFile: each query builds new GitFile objects,
# but an object id always has the same contents. Bounded on purpose, so it
# does not keep the text of every file in memory while the server runs.
@functools.lru_cache(5000)
def _read_lines(repository, object_id: str) -> dict[int, str]:
    return {
        (i + 1): line
        for i, line in enumerate(repository.get_blob_data(object_id).splitlines())
    }


class GitFile:
    """
    Represents a specific version of a file in a Git repository.

    The object_id is the Git object id of the file, which is basically
    its SHA1 hash.
    """

    def __init__(
        self,
        repository,
        path: str,
        absolute_path: str,
        object_id: str,
        score: float,
        commit_messages: list[str],
    ):
        self.repository = repository
        self.path = path
        self.absolute_path = absolute_path
        self.object_id = object_id
        self.commit_hashes = set()
        self.score = score
        self.commit_messages = commit_messages

    def __repr__(self):
        return f"<File {self.path} {self.score}>"

    def add_commit(self, commit_hash: str):
        self.commit_hashes.add(commit_hash)

    def get_metadata(self):
        commit_messages = "\n-".join(sorted(self.commit_messages))
        return f"""###
    Filename: {self.path}
    Commits:
{commit_messages}"""

    @property
    def lines(self) -> dict[int, str]:
        return _read_lines(self.repository, self.object_id)

    def get_chunks(self):
        # TODO: should be turned into a class method on FileChunk
        return [
            FileChunk(self, codeline, chunk, chunk_id)
            for codeline, chunk, chunk_id in _native.get_chunks(
                self.path,
                self.object_id,
                list(self.lines.values()),
                self.get_metadata(),
            )
        ]


class FileChunk:
    def __init__(self, parent: GitFile, codeline: int, chunk: str, chunk_id: str):
        self.path = parent.path
        self.object_id = parent.object_id
        self.codeline = codeline
        self.chunk = chunk
        self.chunk_id = chunk_id
        # Absolute rank of the parent file within its project (0 is the top
        # file); set by Engine.plan_indexing and used for global scheduling.
        self.file_rank = 0

    def __repr__(self) -> str:
        return f"<FileChunk {self.path} {self.codeline}>"
