import datetime
import hashlib
import logging
import math
import subprocess
from collections import defaultdict
from pathlib import Path

from seagoat.gitfile import GitFile
from seagoat.utils.config import get_config_values
from seagoat.utils.file_reader import autodecode_bytes
from seagoat.utils.file_types import is_file_type_supported

logger = logging.getLogger(__name__)

# A recent change counts more than many changes long ago
FRECENCY_DECAY_DAYS = 90


def parse_commit_info(raw_line: str):
    commit_hash, date_str, author, commit_subject = raw_line.split(":::", 3)

    commit_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
    today_utc = datetime.datetime.now(datetime.UTC).date()
    days_passed = max(0, (today_utc - commit_dt.astimezone(datetime.UTC).date()).days)

    return (commit_hash, days_passed, author, commit_subject)


class RepositorySnapshot:
    """One complete, immutable scan of a repository at a single HEAD commit.

    Rankings, file/object metadata and commit history all come from the same
    scan, so a reader holding a snapshot sees one internally consistent view no
    matter what is published afterwards. Nothing mutates a snapshot after it is
    built; "updating" the repository means building and publishing a new one.
    File contents are addressed by git object id, which is immutable, so
    reading them through a snapshot is always consistent with it.
    """

    def __init__(
        self,
        repository: "Repository",
        head: str | None,
        file_changes: dict[str, list],
        frecency_scores: dict[str, float],
        object_ids: dict[str, str],
    ):
        self._repository = repository
        self.head = head
        self.file_changes = file_changes
        self.frecency_scores = frecency_scores
        # Object id (at ``head``) of every scanned file
        self.object_ids = object_ids
        self._ranked_paths = tuple(
            filename
            for filename, _ in sorted(
                frecency_scores.items(), key=lambda item: (-item[1], item[0])
            )
        )

    def has_file(self, filename: str) -> bool:
        return filename in self.frecency_scores

    def is_up_to_date_git_object(self, file_path: str, git_object_id: str) -> bool:
        """Whether the file is, in this snapshot's HEAD, that exact object"""
        return self.object_ids.get(file_path) == git_object_id

    def get_file(self, filename: str) -> GitFile:
        """A GitFile for the version of the file in this snapshot's HEAD"""
        object_id = self.object_ids.get(filename)

        if object_id is None or filename not in self.frecency_scores:
            raise FileNotFoundError(f"{filename} is not part of HEAD")

        return GitFile(
            self._repository,
            filename,
            str(self._repository.path / filename),
            object_id,
            self.frecency_scores[filename],
            [commit[3] for commit in self.file_changes[filename]],
        )

    def top_files(self) -> list[tuple[GitFile, float]]:
        return [
            (self.get_file(filename), self.frecency_scores[filename])
            for filename in self._ranked_paths
        ]


def _is_utf8(path: str) -> bool:
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class Repository:
    def __init__(self, repo_path: str):
        self.path = Path(repo_path)
        self.config = get_config_values(self.path)
        # The last successfully published scan. Replaced as a whole, never
        # mutated, so readers may keep using an older one safely.
        self.snapshot = RepositorySnapshot(self, None, {}, {}, {})
        # HEAD's file list for get_status_hash, cached per HEAD commit
        self._status_head_files: tuple[str | None, frozenset[str]] = (None, frozenset())

    def _is_file_ignored(self, path: str):
        for pattern in self.config["server"]["ignorePatterns"]:
            if Path(path).match(pattern):
                return True

        return False

    def get_blob_data(self, object_id: str) -> str:
        data = subprocess.check_output(
            ["git", "-C", str(self.path), "cat-file", "-p", object_id]
        )
        return autodecode_bytes(data)

    def get_blobs_data(self, object_ids: list[str]) -> dict[str, str]:
        """
        Same as get_blob_data for many objects, with a single git process
        """
        output = subprocess.run(
            ["git", "-C", str(self.path), "cat-file", "--batch"],
            input="".join(f"{object_id}\n" for object_id in object_ids).encode(),
            capture_output=True,
            check=True,
        ).stdout

        blobs = {}
        position = 0
        for object_id in object_ids:
            header_end = output.index(b"\n", position)
            header = output[position:header_end].split()
            position = header_end + 1
            if header[-1] == b"missing":
                continue
            size = int(header[2])
            blobs[object_id] = autodecode_bytes(output[position : position + size])
            # The content is followed by a newline
            position += size + 1

        return blobs

    def get_status_hash(self):
        """A hash of exactly what a plan is built from: HEAD, and which of
        HEAD's files are present in the working tree (see _scan_at_head).

        Uncommitted content edits are left out on purpose: chunks come from
        HEAD blobs, so they change no plan, and hashing them made every
        autosave trigger a full replan (2026-11-06 review, A4). Hashing the
        `git diff` text also failed on a non-UTF-8 edit (A1).
        """
        # A valid unborn repository has no HEAD yet; it still has a stable
        # status for maintenance. A failed HEAD read must continue to raise.
        head = self._get_scan_head()
        cached_head, head_files = self._status_head_files
        if head is None:
            head_files = frozenset()
        elif cached_head != head:
            head_files = frozenset(self._get_files_at_head(head))
            self._status_head_files = (head, head_files)
        present = sorted(self._get_working_tree_files() & head_files)
        combined = "\0".join([head or "", *present])
        return hashlib.sha256(combined.encode("utf-8", "surrogateescape")).hexdigest()

    _MAX_HEAD_VERIFICATION_ATTEMPTS = 3

    @staticmethod
    def _run_scan_command(command, *, check=False, **kwargs):
        # Decode bytes ourselves: text=True normalizes carriage returns in
        # filenames before the NUL-delimited output can be parsed.
        result = subprocess.run(command, capture_output=True, check=check, **kwargs)
        return subprocess.CompletedProcess(
            result.args,
            result.returncode,
            result.stdout.decode("utf-8", errors="surrogateescape"),
            result.stderr.decode("utf-8", errors="surrogateescape"),
        )

    def _run_git(self, *args, check=True):
        return self._run_scan_command(["git", "-C", str(self.path), *args], check=check)

    def _get_scan_head(self) -> str | None:
        """Return the current HEAD commit hash, or None if the repository is
        genuinely unborn (a valid git repository with no commits yet).

        Raises if the directory is not a git working tree or if git itself
        fails, so real git failures never masquerade as an empty scan.
        """
        work_tree_check = self._run_git(
            "rev-parse", "--is-inside-work-tree", check=False
        )
        if work_tree_check.returncode != 0 or work_tree_check.stdout.strip() != "true":
            raise RuntimeError(
                f"{self.path} is not a valid git working tree: "
                f"{work_tree_check.stderr.strip() or work_tree_check.stdout.strip()}"
            )

        head_result = self._run_git("rev-parse", "--verify", "HEAD", check=False)
        if head_result.returncode == 0:
            return head_result.stdout.strip()

        # An unresolved symbolic HEAD is unborn only when its target ref is
        # actually absent. A failed rev-parse for an existing branch is an
        # error, not permission to replace the previous scan with empty data.
        symref_check = self._run_git("symbolic-ref", "--quiet", "HEAD", check=False)
        if symref_check.returncode == 0:
            target = self._run_git(
                "show-ref",
                "--verify",
                "--quiet",
                symref_check.stdout.strip(),
                check=False,
            )
            if target.returncode == 1:
                return None

        raise RuntimeError(
            f"could not resolve HEAD in {self.path}: "
            f"{head_result.stderr.strip() or head_result.stdout.strip()}"
        )

    def _get_files_at_head(self, revision: str = "HEAD") -> dict[str, str]:
        """
        Returns ``{path: git object id}`` for all the files that are part of
        the revision, which are the only files that have a git object id to
        index them by

        Raises instead of returning an empty mapping when git fails, so real
        errors are never mistaken for a repository without files.
        """
        result = self._run_git("ls-tree", "-r", "-z", revision, check=False)

        if result.returncode != 0:
            raise RuntimeError(
                f"git ls-tree failed on {self.path}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        object_ids = {}
        for entry in result.stdout.split("\0"):
            if not entry:
                continue
            # "<mode> <type> <object id>\t<path>"; the path may contain spaces
            metadata, _, path = entry.partition("\t")
            object_ids[path] = metadata.split()[2]

        return object_ids

    def _get_working_tree_files(self) -> set[str]:
        """Return NUL-delimited ripgrep paths from the working tree.

        ripgrep exit code 1 means "no files found", which is a valid empty
        result; exit code 2 (or anything else) means ripgrep itself failed.
        """
        result = self._run_scan_command(
            ["rg", "--no-config", "--files", "-0"], cwd=self.path
        )

        if result.returncode not in (0, 1):
            raise RuntimeError(
                f"ripgrep failed to scan {self.path} "
                f"(exit code {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        return {path for path in result.stdout.split("\0") if path}

    @staticmethod
    def _parse_git_log_stream(stream: str) -> list[tuple[str, tuple]]:
        """Parse the NUL-delimited ``git log --name-only -z`` stream.

        Returns a list of ``(filename, commit_info)`` pairs. Raises on
        malformed/partial output instead of silently producing an empty or
        truncated result.
        """
        fields = stream.split("\0")
        if fields and fields[0] == "":
            fields = fields[1:]

        changes: list[tuple[str, tuple]] = []
        current_commit_info = None
        saw_header = False

        for field in fields:
            if field == "":
                # NUL marker separating commits (or the trailing NUL)
                current_commit_info = None
                continue
            if current_commit_info is None and field.startswith("###"):
                saw_header = True
                # git glues a newline and the first path of the commit to the
                # pretty-format header; the header itself never contains
                # newlines (%%s is a one-line subject).
                header, separator, first_path = field.partition("\n")
                current_commit_info = parse_commit_info(header)
                if separator:
                    changes.append((first_path, current_commit_info))
                continue
            if current_commit_info is None:
                raise RuntimeError(
                    "malformed git log output: path without a commit header"
                )
            changes.append((field, current_commit_info))

        if not saw_header:
            raise RuntimeError("git log produced no commit headers")

        return changes

    @staticmethod
    def _calculate_frecency_scores(file_changes) -> dict[str, float]:
        """Compute frecency scores locally from a dictionary of file changes."""
        return {
            file: sum(
                math.exp(-days_passed / FRECENCY_DECAY_DAYS)
                for _, days_passed, __, ___ in commits
            )
            for file, commits in file_changes.items()
        }

    def _scan_at_head(self, head: str) -> tuple[dict, dict, dict]:
        """Build file_changes, frecency_scores and object ids for one HEAD commit.

        Only the pinned ``head`` revision is read. Any git/rg failure or
        partial git log stream raises here; nothing is published yet.
        """
        # Only files that exist in the working tree (and are not ignored) and
        # are also part of HEAD are considered. Files that appear in the
        # history but are not part of HEAD any more (e.g. deleted files
        # that were re-created as untracked files) can't be indexed.
        head_object_ids = self._get_files_at_head(head)
        files = self._get_working_tree_files() & head_object_ids.keys()
        # A path that is not valid UTF-8 arrives with surrogate escapes: the
        # native chunker (a Rust &str), Chroma metadata and JSON output cannot
        # take it, and one such file used to stop chunking of every file
        # (2026-11-06 review, A1). Skip it, say so, index the rest.
        for path in sorted(path for path in files if not _is_utf8(path)):
            logger.warning(
                "Skipping %r: its file name is not valid UTF-8",
                path.encode("utf-8", "surrogateescape"),
            )
            files.discard(path)

        cmd = [
            "git",
            "-C",
            str(self.path),
            "log",
            "--name-only",
            "-z",
            "--pretty=format:%x00###%h:::%ai:::%an <%ae>:::%s",
            "--no-merges",
            *self._git_log_extra_options(),
            head,
        ]

        result = self._run_scan_command(cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"git log failed on {self.path}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        file_changes = defaultdict(list)
        for filename, commit_info in self._parse_git_log_stream(result.stdout):
            if (
                not is_file_type_supported(filename)
                or self._is_file_ignored(filename)
                or filename not in files
            ):
                continue
            file_changes[filename].append(commit_info)

        return (
            file_changes,
            self._calculate_frecency_scores(file_changes),
            {path: head_object_ids[path] for path in file_changes},
        )

    def scan(self) -> RepositorySnapshot:
        """Scan the repository at a single pinned HEAD revision, without
        publishing anything.

        Returns a complete, immutable snapshot. On any failure (failed git/rg
        command, partial git log stream, or a HEAD that moved while scanning)
        raises; the previously published snapshot is not touched.
        """
        for _ in range(self._MAX_HEAD_VERIFICATION_ATTEMPTS):
            head = self._get_scan_head()
            if head is None:
                # Verify unborn HEAD too: the first commit may arrive while
                # this scan is running.
                file_changes, frecency_scores, object_ids = defaultdict(list), {}, {}
            else:
                file_changes, frecency_scores, object_ids = self._scan_at_head(head)

            if self._get_scan_head() == head:
                return RepositorySnapshot(
                    self, head, file_changes, frecency_scores, object_ids
                )

            # HEAD moved while we were reading; retry against the new HEAD.

        raise RuntimeError(
            "repository HEAD kept changing during analysis; "
            "refusing to publish possibly inconsistent file metadata"
        )

    def publish(self, snapshot: RepositorySnapshot) -> None:
        """Make a completed snapshot the repository's current one."""
        self.snapshot = snapshot

    def analyze_files(self):
        """Scan the repository and publish the result as the current snapshot.

        On any failure raises and leaves the previous complete snapshot intact.
        """
        self.publish(self.scan())

    def _git_log_extra_options(self):
        cmd = []

        if (max_commits := self.config["server"]["readMaxCommits"]) is not None:
            cmd.append(f"--max-count={max_commits}")

        return cmd

    def top_files(self):
        """Ranked files of the currently published snapshot"""
        return self.snapshot.top_files()

    def get_file(self, filename: str):
        """
        Returns a GitFile object with the version of the file in the HEAD of
        the currently published snapshot
        """
        return self.snapshot.get_file(filename)
