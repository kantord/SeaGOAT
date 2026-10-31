"""A git repository with a few made-up commits, for tests to add more to."""

import os
from datetime import UTC, datetime, timedelta

from git.repo import Repo
from git.util import Actor


class MockRepo(Repo):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake_commit_date = datetime.now(UTC) - timedelta(days=400)
        self.actors = {
            "John Doe": Actor("John Doe", "jdoe@example.com"),
            "Alice Smith": Actor("Alice Smith", "asmith@example.com"),
            "Charlie Brown": Actor("Charlie Brown", "cbrown@example.com"),
        }

    def tick_fake_date(self, days=0, hours=0, minutes=0):
        delta = timedelta(days=days, hours=hours, minutes=minutes)
        self.fake_commit_date += delta

    def add_fake_data(self):
        file_changes = [
            {
                "name": "file1.md",
                "contents": [
                    "# Markdown file\nThis is an example Markdown file.",
                    (
                        "# Markdown file\nThis is an example Markdown file. Updated. \n"
                        + "HTML is for markup, but it's complicated. Markdown is simpler."
                    ),
                ],
                "authors": [
                    self.actors["John Doe"],
                    self.actors["Alice Smith"],
                ],
                "commit_messages": [
                    "Initial commit for Markdown file",
                    "Update to Markdown file",
                ],
            },
            {
                "name": "file2.py",
                "contents": [
                    "# This is an example Python file",
                    "# This is an updated example Python file",
                ],
                "authors": [
                    self.actors["Alice Smith"],
                    self.actors["Charlie Brown"],
                ],
                "commit_messages": [
                    "Initial commit for Python file",
                    "Update to Python file",
                ],
            },
            {
                "name": "file3.py",
                "contents": ["# This is another example Python file"],
                "authors": [self.actors["Charlie Brown"]],
                "commit_messages": ["Initial commit for another Python file"],
            },
            {
                "name": "file4.js",
                "contents": [
                    "// This is an example JavaScript file",
                    "// This is an updated example JavaScript file",
                    "// This is a second updated example JavaScript file",
                ],
                "authors": [
                    self.actors["John Doe"],
                    self.actors["Alice Smith"],
                    self.actors["Charlie Brown"],
                ],
                "commit_messages": [
                    "Initial commit for JavaScript file",
                    "Update to JavaScript file",
                    "Second update to JavaScript file",
                ],
            },
            {
                "name": "file4.md",
                "contents": [
                    "// This is an example JavaScript file",
                    "// This is an example JavaScript file 2",
                    "// This is an updated example JavaScript file",
                    "// This is a second updated example JavaScript file",
                ],
                "authors": [
                    self.actors["John Doe"],
                    self.actors["John Doe"],
                    self.actors["Alice Smith"],
                    self.actors["Charlie Brown"],
                ],
                "commit_messages": [
                    "Initial commit for JavaScript file",
                    "Initial commit for JavaScript file 2",
                    "Update to JavaScript file",
                    "Second update to JavaScript file",
                ],
            },
        ]

        for file_change in file_changes:
            for i in range(len(file_change["contents"])):
                self.add_file_change_commit(
                    file_change["name"],
                    file_change["contents"][i],
                    file_change["commit_messages"][i],
                    author=file_change["authors"][i],
                )
                self.tick_fake_date(days=1)

    def add_file_change_commit(
        self,
        file_name: str,
        contents: str,
        commit_message: str,
        author: Actor | None = None,
        encoding="utf-8",
    ) -> str:
        # Create parent directory if it doesn't exist:
        parent_folder = os.path.dirname(os.path.join(self.working_dir, file_name))
        if parent_folder:
            os.makedirs(parent_folder, exist_ok=True)

        file_path = os.path.join(self.working_dir, file_name)

        with open(file_path, "w", encoding=encoding) as output_file:
            output_file.write(contents)
        self.index.add([file_name])

        return self._commit_changes(commit_message, author)

    def _commit_changes(self, commit_message: str, author: Actor | None) -> str:
        author = author or self.actors["John Doe"]
        return self.index.commit(
            commit_message,
            author=author,
            committer=author,
            author_date=self.fake_commit_date,
            commit_date=self.fake_commit_date,
            skip_hooks=True,
        ).hexsha

    def add_file_delete_commit(
        self,
        file_name: str,
        commit_message: str,
        author: Actor | None = None,
    ) -> str:
        file_path = os.path.join(self.working_dir, file_name)

        os.unlink(file_path)
        self.index.remove(file_name)

        return self._commit_changes(commit_message, author)
