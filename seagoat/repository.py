import datetime
import math
import subprocess
from collections import defaultdict
from pathlib import Path

from seagoat.common import SUPPORTED_FILE_TYPES
from seagoat.file import File


def parse_commit_info(raw_line: str):
    commit_hash, date_str, author, commit_subject = raw_line.split(":::")

    commit_date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z").date()
    today = datetime.date.today()
    days_passed = (today - commit_date).days

    return (commit_hash, days_passed, author, commit_subject)


class Repository:
    def __init__(self, repo_path: str):
        self.path = Path(repo_path)
        self.file_changes = defaultdict(list)
        self.frecency_scores = {}

    def analyze_files(self):
        cmd = [
            "git",
            "-C",
            self.path,
            "log",
            "--name-only",
            "--pretty=format:###%h:::%ai:::%an <%ae>:::%s",
            "--no-merges",
        ]

        self.file_changes.clear()

        current_commit_info = None
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as proc:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if ":::" in line:
                    current_commit_info = parse_commit_info(line)
                elif line:
                    filename = line

                    if Path(filename).suffix not in SUPPORTED_FILE_TYPES:
                        continue

                    if not (self.path / filename).exists():
                        continue

                    self.file_changes[filename].append(current_commit_info)

        self._compute_frecency()

    def _compute_frecency(self):
        self.frecency_scores = {}
        for file, commits in self.file_changes.items():
            score = sum(
                1 / (math.log(days_passed + 2, 2))
                for _, days_passed, __, ___ in commits
            )
            self.frecency_scores[file] = score

    def top_files(self):
        return [
            (self.get_file(filename), score)
            for filename, score in sorted(
                self.frecency_scores.items(), key=lambda x: x[0][1]
            )
        ]

    def get_file(self, filename: str):
        return File(
            filename,
            str(self.path / filename),
            self.frecency_scores[filename],
            [commit[3] for commit in self.file_changes[filename]],
        )
