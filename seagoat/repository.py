import datetime
import hashlib
import math
import subprocess
from collections import defaultdict
from pathlib import Path

from seagoat.gitfile import GitFile
from seagoat.utils.config import get_config_values
from seagoat.utils.file_reader import autodecode_bytes
from seagoat.utils.file_types import is_file_type_supported

# A recent change counts more than many changes long ago
FRECENCY_DECAY_DAYS = 90


def parse_commit_info(raw_line: str):
    commit_hash, date_str, author, commit_subject = raw_line.split(":::", 3)

    commit_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
    today_utc = datetime.datetime.now(datetime.UTC).date()
    days_passed = max(0, (today_utc - commit_dt.astimezone(datetime.UTC).date()).days)

    return (commit_hash, days_passed, author, commit_subject)


class Repository:
    def __init__(self, repo_path: str):
        self.path = Path(repo_path)
        self.config = get_config_values(self.path)
        self.file_changes = defaultdict(list)
        self.frecency_scores = {}

    def _get_head_hash(self):
        return subprocess.check_output(
            ["git", "-C", str(self.path), "rev-parse", "HEAD"],
            text=True,
        ).strip()

    def _get_working_tree_diff(self):
        return subprocess.check_output(
            ["git", "-C", str(self.path), "diff"],
            text=True,
        ).strip()

    def _is_file_ignored(self, path: str):
        for pattern in self.config["server"]["ignorePatterns"]:
            if Path(path).match(pattern):
                return True

        return False

    def get_file_object_id(self, file_path: str) -> str | None:
        """
        Returns the git object id for the current version
        of a file, or None if the file is not part of HEAD
        (for example a file that was deleted from the repository,
        but exists in the working tree as an untracked file)
        """
        ls_tree_output = subprocess.check_output(
            [
                "git",
                "-C",
                str(self.path),
                "ls-tree",
                "HEAD",
                # --: a path starting with "-" is a path, not an option
                "--",
                str(file_path),
            ],
            text=True,
        ).split()

        if len(ls_tree_output) < 3:
            return None

        return ls_tree_output[2]

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

    def is_up_to_date_git_object(self, file_path: str, git_object_id: str):
        return self.get_file_object_id(file_path) == git_object_id

    def get_status_hash(self):
        combined = self._get_head_hash() + self._get_working_tree_diff()
        return hashlib.sha256(combined.encode()).hexdigest()

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

    def _get_files_at_head(self, revision: str = "HEAD") -> set[str]:
        """
        Returns the paths of all the files that are part of HEAD, which
        are the only files that have a git object id to index them by

        Raises instead of returning an empty set when git fails, so real
        errors are never mistaken for a repository without files.
        """
        result = self._run_git(
            "ls-tree", "-r", "--name-only", "-z", revision, check=False
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"git ls-tree failed on {self.path}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        return {path for path in result.stdout.split("\0") if path}

    def _get_working_tree_files(self) -> set[str]:
        """Return NUL-delimited ripgrep paths from the working tree.

        ripgrep exit code 1 means "no files found", which is a valid empty
        result; exit code 2 (or anything else) means ripgrep itself failed.
        """
        result = self._run_scan_command(["rg", "--files", "-0"], cwd=self.path)

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

    def _scan_at_head(self, head: str) -> tuple[dict, dict]:
        """Build file_changes/frecency_scores dictionaries for one HEAD commit.

        Only the pinned ``head`` revision is read. Any git/rg failure or
        partial git log stream raises here; nothing is published yet.
        """
        # Only files that exist in the working tree (and are not ignored) and
        # are also part of HEAD are considered. Files that appear in the
        # history but are not part of HEAD any more (e.g. deleted files
        # that were re-created as untracked files) can't be indexed.
        files = self._get_working_tree_files() & self._get_files_at_head(head)

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

        return file_changes, self._calculate_frecency_scores(file_changes)

    def analyze_files(self):
        """Scan the repository at a single pinned HEAD revision.

        On success, publishes the completed file_changes and frecency_scores
        dictionaries after validation. On any failure (failed git/rg command,
        partial git log stream, or a HEAD that moved while scanning) raises
        and leaves the previous complete metadata intact.
        """
        for _ in range(self._MAX_HEAD_VERIFICATION_ATTEMPTS):
            head = self._get_scan_head()
            if head is None:
                # Verify unborn HEAD too: the first commit may arrive while
                # this scan is running.
                file_changes, frecency_scores = defaultdict(list), {}
            else:
                file_changes, frecency_scores = self._scan_at_head(head)

            if self._get_scan_head() == head:
                self.file_changes = file_changes
                self.frecency_scores = frecency_scores
                return

            # HEAD moved while we were reading; retry against the new HEAD.

        raise RuntimeError(
            "repository HEAD kept changing during analysis; "
            "refusing to publish possibly inconsistent file metadata"
        )

    def _git_log_extra_options(self):
        cmd = []

        if (max_commits := self.config["server"]["readMaxCommits"]) is not None:
            cmd.append(f"--max-count={max_commits}")

        return cmd

    def _compute_frecency(self):
        self.frecency_scores = self._calculate_frecency_scores(self.file_changes)

    def top_files(self):
        return [
            (self.get_file(filename), score)
            for filename, score in sorted(
                self.frecency_scores.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

    def get_file(self, filename: str):
        """
        Returns a GitFile object with the current version of the file
        """
        object_id = self.get_file_object_id(filename)

        if object_id is None:
            raise FileNotFoundError(f"{filename} is not part of HEAD")

        return GitFile(
            self,
            filename,
            str(self.path / filename),
            object_id,
            self.frecency_scores[filename],
            [commit[3] for commit in self.file_changes[filename]],
        )
