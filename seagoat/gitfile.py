import functools

from seagoat import _native


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
    # Bounded on purpose: caching on the instance instead would keep the
    # text of every file in memory for as long as the server runs
    @functools.lru_cache(5000)  # noqa: B019
    def lines(self) -> dict[int, str]:
        lines = {
            (i + 1): line
            for i, line in enumerate(
                self.repository.get_blob_data(self.object_id).splitlines()
            )
        }

        return lines

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

    def __repr__(self) -> str:
        return f"<FileChunk {self.path} {self.codeline}>"
