"""A made-up habit tracker repository, built entirely by the test suite.

The repository is deterministic: every commit uses the same author and
committer and a fixed date, so building in two empty directories yields the
same HEAD commit ID. No network access is needed.
"""

import os
import subprocess

AUTHOR_NAME = "Test Author"
AUTHOR_EMAIL = "test@example.com"


def _git_env(**extra: str) -> dict:
    env = os.environ.copy()
    # Ignore the developer's git configuration so no commit signing, hooks or
    # other settings leak into the made-up commits and the repo stays
    # reproducible (same commit IDs no matter who builds it).
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            **extra,
        }
    )
    return env


def _run_git(repo_path: str, *args: str, env: dict | None = None):
    subprocess.run(
        ["git", "-C", repo_path, *args],
        check=True,
        capture_output=True,
        text=True,
        env=env if env is not None else _git_env(),
    )


def _commit_env(date: str) -> dict:
    return _git_env(
        GIT_AUTHOR_NAME=AUTHOR_NAME,
        GIT_AUTHOR_EMAIL=AUTHOR_EMAIL,
        GIT_AUTHOR_DATE=date,
        GIT_COMMITTER_NAME=AUTHOR_NAME,
        GIT_COMMITTER_EMAIL=AUTHOR_EMAIL,
        GIT_COMMITTER_DATE=date,
    )


def build(repo_path: str) -> str:
    """Create the made-up project in ``repo_path`` and return its path."""
    os.makedirs(repo_path, exist_ok=True)
    _run_git(repo_path, "init", "-b", "master")

    current_branch = "master"
    for commit in COMMITS:
        if commit.get("branch") and commit["branch"] != current_branch:
            _run_git(repo_path, "switch", "-c", commit["branch"])
            current_branch = commit["branch"]

        if commit.get("merge"):
            _run_git(repo_path, "switch", "master")
            _run_git(
                repo_path,
                "merge",
                "--no-ff",
                commit["merge"],
                "-m",
                commit["message"],
                env=_commit_env(commit["date"]),
            )
            current_branch = "master"
            continue

        env = _commit_env(commit["date"])
        for file_path, content in commit["files"].items():
            full_path = os.path.join(repo_path, file_path)
            os.makedirs(os.path.dirname(full_path) or repo_path, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file:
                file.write(content)
        _run_git(repo_path, "add", "-A", env=env)
        _run_git(repo_path, "commit", "-m", commit["message"], env=env)

    return repo_path


COMMITS = [
    {
        "message": "Initialize the streak project skeleton",
        "date": "2024-01-05T10:00:00+00:00",
        "files": {
            "README.md": """# streak — a command-line habit tracker

streak is a small command-line habit tracker written in Python. It keeps your
habits in a local JSON database, tracks your streaks, and prints a colored
report so you can see your progress at a glance.

## Features

- Add, list, check, and delete habits from the terminal
- Automatic streak and best-streak tracking
- A colored terminal report with configurable color themes
- Works fully offline; your data never leaves your machine

## Usage

Start by adding a habit:

```sh
streak add "drink two liters of water" --daily
```

Mark a habit as done for today:

```sh
streak check "drink two liters of water"
```

List all habits with their current streaks:

```sh
streak list
```

## Configuration

streak stores its data in `~/.local/share/streak/habits.json`. The report
colors and other options live in `~/.config/streak/config.toml`.

## License

MIT
""",
            "pyproject.toml": """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "streak"
version = "0.1.0"
description = "A command-line habit tracker"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "Test Author", email = "test@example.com" }]
dependencies = [
    "click>=8.1,<9",
    "platformdirs>=4,<5",
]

[project.scripts]
streak = "streak.cli:main"

[tool.setuptools]
packages = ["streak"]
""",
            "streak/__init__.py": '''"""streak — a command-line habit tracker."""

__version__ = "0.1.0"
''',
        },
    },
    {
        "message": "Add JSON storage for habits",
        "date": "2024-01-07T09:30:00+00:00",
        "files": {
            "streak/storage.py": '''"""JSON file storage for habits."""

import json
from datetime import date
from pathlib import Path


class StorageError(Exception):
    """Raised when the habit database cannot be read or written."""


class HabitStore:
    """Loads and saves the habit database as a single JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"habits": {}, "settings": {}}
        self.load()

    def load(self):
        """Read the database from disk. A missing file stays empty."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as file:
            stored = json.load(file)
        self.data["habits"] = stored.get("habits", {})
        self.data["settings"] = stored.get("settings", {})

    def save(self):
        """Write the database back to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, sort_keys=True)

    def add_habit(self, name: str, frequency: str = "daily") -> dict:
        """Create a new habit and return it."""
        if name in self.data["habits"]:
            raise StorageError(f"habit {name!r} already exists")
        habit = {
            "name": name,
            "frequency": frequency,
            "created": date.today().isoformat(),
            "completions": [],
            "reminder_time": None,
        }
        self.data["habits"][name] = habit
        self.save()
        return habit

    def get_habit(self, name: str) -> dict:
        try:
            return self.data["habits"][name]
        except KeyError as error:
            raise StorageError(f"unknown habit {name!r}") from error

    def list_habits(self) -> list:
        """Return all habits sorted by name."""
        return sorted(self.data["habits"].values(), key=lambda habit: habit["name"])
''',
        },
    },
    {
        "message": "Add the CLI commands to add and list habits",
        "date": "2024-01-10T14:15:00+00:00",
        "files": {
            "streak/cli.py": '''"""Command-line interface for streak."""

import click
import platformdirs

from streak.storage import HabitStore, StorageError


def _data_file():
    return platformdirs.user_data_dir("streak") / "habits.json"


def _load_store() -> HabitStore:
    return HabitStore(_data_file())


@click.group()
def main():
    """streak — a command-line habit tracker."""


@main.command()
@click.argument("name")
@click.option(
    "--daily", "frequency", flag_value="daily", default=True, help="Repeat every day."
)
@click.option(
    "--weekly", "frequency", flag_value="weekly", help="Repeat once a week."
)
def add(name, frequency):
    """Add a new habit with the given NAME."""
    try:
        habit = _load_store().add_habit(name, frequency)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Added habit {habit['name']!r} ({habit['frequency']}).")


@main.command()
def list():
    """List all habits with their frequency."""
    store = _load_store()
    for habit in store.list_habits():
        click.echo(f"- {habit['name']} ({habit['frequency']})")
''',
        },
    },
    {
        "message": "Track completion history and compute streaks",
        "date": "2024-01-13T11:00:00+00:00",
        "files": {
            "streak/storage.py": '''"""JSON file storage for habits and their completion history."""

import json
from datetime import date, timedelta
from pathlib import Path


class StorageError(Exception):
    """Raised when the habit database cannot be read or written."""


class HabitStore:
    """Loads and saves the habit database as a single JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"habits": {}, "settings": {}}
        self.load()

    def load(self):
        """Read the database from disk. A missing file stays empty."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as file:
            stored = json.load(file)
        self.data["habits"] = stored.get("habits", {})
        self.data["settings"] = stored.get("settings", {})

    def save(self):
        """Write the database back to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, sort_keys=True)

    def add_habit(self, name: str, frequency: str = "daily") -> dict:
        """Create a new habit and return it."""
        if name in self.data["habits"]:
            raise StorageError(f"habit {name!r} already exists")
        habit = {
            "name": name,
            "frequency": frequency,
            "created": date.today().isoformat(),
            "completions": [],
            "reminder_time": None,
        }
        self.data["habits"][name] = habit
        self.save()
        return habit

    def get_habit(self, name: str) -> dict:
        try:
            return self.data["habits"][name]
        except KeyError as error:
            raise StorageError(f"unknown habit {name!r}") from error

    def delete_habit(self, name: str):
        """Remove a habit and its whole history."""
        if name not in self.data["habits"]:
            raise StorageError(f"unknown habit {name!r}")
        del self.data["habits"][name]
        self.save()

    def check_in(self, name: str, day: date):
        """Record a completion for a habit on the given day."""
        habit = self.get_habit(name)
        day_text = day.isoformat()
        if day_text in habit["completions"]:
            raise StorageError(f"habit {name!r} was already checked on {day_text}")
        habit["completions"].append(day_text)
        self.save()

    def set_reminder(self, name: str, reminder_time: str | None):
        """Configure the daily reminder time for a habit."""
        habit = self.get_habit(name)
        habit["reminder_time"] = reminder_time
        self.save()

    def list_habits(self) -> list:
        """Return all habits sorted by name."""
        return sorted(self.data["habits"].values(), key=lambda habit: habit["name"])


def compute_streak(completions: list, today: date) -> int:
    """Return how many consecutive days a habit was completed up to today."""
    completed = set(completions)
    streak = 0
    day = today
    while day.isoformat() in completed:
        streak += 1
        day -= timedelta(days=1)
    return streak
''',
        },
    },
    {
        "message": "Add the check-in command to mark habits as done",
        "date": "2024-01-16T16:40:00+00:00",
        "files": {
            "streak/cli.py": '''"""Command-line interface for streak."""

from datetime import date

import click
import platformdirs

from streak.storage import HabitStore, StorageError


def _data_file():
    return platformdirs.user_data_dir("streak") / "habits.json"


def _load_store() -> HabitStore:
    return HabitStore(_data_file())


@click.group()
def main():
    """streak — a command-line habit tracker."""


@main.command()
@click.argument("name")
@click.option(
    "--daily", "frequency", flag_value="daily", default=True, help="Repeat every day."
)
@click.option(
    "--weekly", "frequency", flag_value="weekly", help="Repeat once a week."
)
def add(name, frequency):
    """Add a new habit with the given NAME."""
    try:
        habit = _load_store().add_habit(name, frequency)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Added habit {habit['name']!r} ({habit['frequency']}).")


@main.command()
@click.argument("name")
def check(name):
    """Mark NAME as completed today."""
    try:
        _load_store().check_in(name, date.today())
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Checked {name!r} for today.")


@main.command()
def list():
    """List all habits with their frequency."""
    store = _load_store()
    for habit in store.list_habits():
        click.echo(f"- {habit['name']} ({habit['frequency']})")
''',
        },
    },
    {
        "message": "Add a terminal report command showing habit streaks",
        "date": "2024-01-19T08:20:00+00:00",
        "files": {
            "streak/report.py": '''"""Renders a terminal report of habit progress."""

from datetime import date

from streak.storage import HabitStore, compute_streak


def render_report(store: HabitStore, today: date | None = None) -> list:
    """Render the report as one line per habit plus a summary."""
    today = today or date.today()
    habits = store.list_habits()
    if not habits:
        return ["No habits yet. Add one with 'streak add'."]

    lines = ["Habit report"]
    for habit in habits:
        streak = compute_streak(habit["completions"], today)
        if streak:
            status = f"{streak} day streak"
        else:
            status = "not started today"
        lines.append(f"{habit['name']}: {status}")
    lines.append(f"Total habits: {len(habits)}")
    return lines
''',
            "streak/cli.py": '''"""Command-line interface for streak."""

from datetime import date

import click
import platformdirs

from streak.report import render_report
from streak.storage import HabitStore, StorageError


def _data_file():
    return platformdirs.user_data_dir("streak") / "habits.json"


def _load_store() -> HabitStore:
    return HabitStore(_data_file())


@click.group()
def main():
    """streak — a command-line habit tracker."""


@main.command()
@click.argument("name")
@click.option(
    "--daily", "frequency", flag_value="daily", default=True, help="Repeat every day."
)
@click.option(
    "--weekly", "frequency", flag_value="weekly", help="Repeat once a week."
)
def add(name, frequency):
    """Add a new habit with the given NAME."""
    try:
        habit = _load_store().add_habit(name, frequency)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Added habit {habit['name']!r} ({habit['frequency']}).")


@main.command()
@click.argument("name")
def check(name):
    """Mark NAME as completed today."""
    try:
        _load_store().check_in(name, date.today())
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Checked {name!r} for today.")


@main.command()
def list():
    """List all habits with their frequency."""
    store = _load_store()
    for habit in store.list_habits():
        click.echo(f"- {habit['name']} ({habit['frequency']})")


@main.command()
def report():
    """Print a report of your habit progress."""
    for line in render_report(_load_store()):
        click.echo(line)
''',
            "README.md": """# streak — a command-line habit tracker

streak is a small command-line habit tracker written in Python. It keeps your
habits in a local JSON database, tracks your streaks, and prints a colored
report so you can see your progress at a glance.

## Features

- Add, list, check, and delete habits from the terminal
- Automatic streak and best-streak tracking
- A colored terminal report with configurable color themes
- Works fully offline; your data never leaves your machine

## Usage

Start by adding a habit:

```sh
streak add "drink two liters of water" --daily
```

Mark a habit as done for today:

```sh
streak check "drink two liters of water"
```

List all habits with their current streaks:

```sh
streak list
```

### The report

The `streak report` command prints a colored overview of your habits:

```sh
streak report
```

## Configuration

streak stores its data in `~/.local/share/streak/habits.json`. The report
colors and other options live in `~/.config/streak/config.toml`.

## License

MIT
""",
        },
    },
    {
        "message": "Schedule desktop reminders for habits that are due",
        "date": "2024-01-22T12:10:00+00:00",
        "files": {
            "streak/reminders.py": '''"""Schedules desktop reminders for habits that are due today."""

import subprocess
import time
from datetime import datetime, time as clock_time

from streak.storage import HabitStore


class ReminderScheduler:
    """Periodically checks for due habits and raises desktop notifications."""

    def __init__(self, store: HabitStore, interval_minutes: int = 15):
        self.store = store
        self.interval_minutes = interval_minutes

    def run_forever(self):
        """Check for due habits every interval until interrupted."""
        while True:
            self.check_due_habits()
            time.sleep(self.interval_minutes * 60)

    def check_due_habits(self):
        """Notify the user about every habit whose reminder time has passed."""
        now = datetime.now().time()
        for habit in self.store.list_habits():
            if self._is_due(habit, now):
                self._notify(habit)

    def _is_due(self, habit: dict, now: clock_time) -> bool:
        """A habit is due when a reminder time is set and has already passed."""
        reminder = habit.get("reminder_time")
        if not reminder:
            return False
        hour, minute = (int(part) for part in reminder.split(":"))
        return clock_time(hour, minute) <= now

    def _notify(self, habit: dict):
        """Show a desktop notification using notify-send."""
        message = f"Remember to complete your habit: {habit['name']}"
        subprocess.run(
            ["notify-send", "--app-name=streak", "Habit reminder", message],
            check=False,
        )
''',
            "streak/cli.py": '''"""Command-line interface for streak."""

from datetime import date

import click
import platformdirs

from streak.reminders import ReminderScheduler
from streak.report import render_report
from streak.storage import HabitStore, StorageError


def _data_file():
    return platformdirs.user_data_dir("streak") / "habits.json"


def _load_store() -> HabitStore:
    return HabitStore(_data_file())


@click.group()
def main():
    """streak — a command-line habit tracker."""


@main.command()
@click.argument("name")
@click.option(
    "--daily", "frequency", flag_value="daily", default=True, help="Repeat every day."
)
@click.option(
    "--weekly", "frequency", flag_value="weekly", help="Repeat once a week."
)
def add(name, frequency):
    """Add a new habit with the given NAME."""
    try:
        habit = _load_store().add_habit(name, frequency)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Added habit {habit['name']!r} ({habit['frequency']}).")


@main.command()
@click.argument("name")
def check(name):
    """Mark NAME as completed today."""
    try:
        _load_store().check_in(name, date.today())
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Checked {name!r} for today.")


@main.command()
def list():
    """List all habits with their frequency."""
    store = _load_store()
    for habit in store.list_habits():
        click.echo(f"- {habit['name']} ({habit['frequency']})")


@main.command()
def report():
    """Print a report of your habit progress."""
    for line in render_report(_load_store()):
        click.echo(line)


@main.command()
@click.option(
    "--interval",
    "interval_minutes",
    default=15,
    show_default=True,
    help="Minutes between reminder checks.",
)
def daemon(interval_minutes):
    """Run in the background and send desktop reminders."""
    ReminderScheduler(_load_store(), interval_minutes).run_forever()
''',
        },
    },
    {
        "message": "Make the reminder interval configurable",
        "date": "2024-01-25T15:50:00+00:00",
        "files": {
            "streak/storage.py": '''"""JSON file storage for habits and their completion history."""

import json
from datetime import date, timedelta
from pathlib import Path


class StorageError(Exception):
    """Raised when the habit database cannot be read or written."""


class HabitStore:
    """Loads and saves the habit database as a single JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"habits": {}, "settings": {}}
        self.load()

    def load(self):
        """Read the database from disk. A missing file stays empty."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as file:
            stored = json.load(file)
        self.data["habits"] = stored.get("habits", {})
        self.data["settings"] = stored.get("settings", {})

    def save(self):
        """Write the database back to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, sort_keys=True)

    def add_habit(self, name: str, frequency: str = "daily") -> dict:
        """Create a new habit and return it."""
        if name in self.data["habits"]:
            raise StorageError(f"habit {name!r} already exists")
        habit = {
            "name": name,
            "frequency": frequency,
            "created": date.today().isoformat(),
            "completions": [],
            "reminder_time": None,
        }
        self.data["habits"][name] = habit
        self.save()
        return habit

    def get_habit(self, name: str) -> dict:
        try:
            return self.data["habits"][name]
        except KeyError as error:
            raise StorageError(f"unknown habit {name!r}") from error

    def delete_habit(self, name: str):
        """Remove a habit and its whole history."""
        if name not in self.data["habits"]:
            raise StorageError(f"unknown habit {name!r}")
        del self.data["habits"][name]
        self.save()

    def check_in(self, name: str, day: date):
        """Record a completion for a habit on the given day."""
        habit = self.get_habit(name)
        day_text = day.isoformat()
        if day_text in habit["completions"]:
            raise StorageError(f"habit {name!r} was already checked on {day_text}")
        habit["completions"].append(day_text)
        self.save()

    def set_reminder(self, name: str, reminder_time: str | None):
        """Configure the daily reminder time for a habit."""
        habit = self.get_habit(name)
        habit["reminder_time"] = reminder_time
        self.save()

    def set_setting(self, key: str, value):
        """Store a configuration value in the database."""
        self.data["settings"][key] = value
        self.save()

    def get_setting(self, key: str, default=None):
        """Read a configuration value, falling back to default."""
        return self.data["settings"].get(key, default)

    def list_habits(self) -> list:
        """Return all habits sorted by name."""
        return sorted(self.data["habits"].values(), key=lambda habit: habit["name"])


def compute_streak(completions: list, today: date) -> int:
    """Return how many consecutive days a habit was completed up to today."""
    completed = set(completions)
    streak = 0
    day = today
    while day.isoformat() in completed:
        streak += 1
        day -= timedelta(days=1)
    return streak
''',
            "streak/reminders.py": '''"""Schedules desktop reminders for habits that are due today."""

import subprocess
import time
from datetime import datetime, time as clock_time

from streak.storage import HabitStore

DEFAULT_INTERVAL_MINUTES = 15


class ReminderScheduler:
    """Periodically checks for due habits and raises desktop notifications."""

    def __init__(self, store: HabitStore, interval_minutes: int | None = None):
        self.store = store
        self.interval_minutes = interval_minutes or store.get_setting(
            "reminder_interval", DEFAULT_INTERVAL_MINUTES
        )

    def run_forever(self):
        """Check for due habits every interval until interrupted."""
        while True:
            self.check_due_habits()
            time.sleep(self.interval_minutes * 60)

    def check_due_habits(self):
        """Notify the user about every habit whose reminder time has passed."""
        now = datetime.now().time()
        for habit in self.store.list_habits():
            if self._is_due(habit, now):
                self._notify(habit)

    def _is_due(self, habit: dict, now: clock_time) -> bool:
        """A habit is due when a reminder time is set and has already passed."""
        reminder = habit.get("reminder_time")
        if not reminder:
            return False
        hour, minute = (int(part) for part in reminder.split(":"))
        return clock_time(hour, minute) <= now

    def _notify(self, habit: dict):
        """Show a desktop notification using notify-send."""
        message = f"Remember to complete your habit: {habit['name']}"
        subprocess.run(
            ["notify-send", "--app-name=streak", "Habit reminder", message],
            check=False,
        )
''',
            "streak/cli.py": '''"""Command-line interface for streak."""

from datetime import date

import click
import platformdirs

from streak.reminders import ReminderScheduler
from streak.report import render_report
from streak.storage import HabitStore, StorageError


def _data_file():
    return platformdirs.user_data_dir("streak") / "habits.json"


def _load_store() -> HabitStore:
    return HabitStore(_data_file())


@click.group()
def main():
    """streak — a command-line habit tracker."""


@main.command()
@click.argument("name")
@click.option(
    "--daily", "frequency", flag_value="daily", default=True, help="Repeat every day."
)
@click.option(
    "--weekly", "frequency", flag_value="weekly", help="Repeat once a week."
)
def add(name, frequency):
    """Add a new habit with the given NAME."""
    try:
        habit = _load_store().add_habit(name, frequency)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Added habit {habit['name']!r} ({habit['frequency']}).")


@main.command()
@click.argument("name")
def check(name):
    """Mark NAME as completed today."""
    try:
        _load_store().check_in(name, date.today())
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Checked {name!r} for today.")


@main.command()
def list():
    """List all habits with their frequency."""
    store = _load_store()
    for habit in store.list_habits():
        click.echo(f"- {habit['name']} ({habit['frequency']})")


@main.command()
def report():
    """Print a report of your habit progress."""
    for line in render_report(_load_store()):
        click.echo(line)


@main.command()
@click.option(
    "--interval",
    "interval_minutes",
    default=None,
    help="Minutes between reminder checks. Defaults to the configured value.",
)
def daemon(interval_minutes):
    """Run in the background and send desktop reminders."""
    ReminderScheduler(_load_store(), interval_minutes).run_forever()
''',
        },
    },
    {
        "message": "Add colored themes to the terminal report",
        "date": "2024-01-28T09:45:00+00:00",
        "files": {
            "streak/report.py": r'''"""Renders a colored terminal report of habit progress."""

from datetime import date

from streak.storage import HabitStore, compute_streak

# Color themes map semantic roles to ANSI escape codes. Users can pick one
# with the --theme option of the report command.
COLOR_THEMES = {
    "default": {
        "heading": "\033[1;37m",
        "positive": "\033[1;32m",
        "warning": "\033[1;33m",
        "negative": "\033[1;31m",
        "muted": "\033[2m",
        "reset": "\033[0m",
    },
    "ocean": {
        "heading": "\033[1;36m",
        "positive": "\033[1;34m",
        "warning": "\033[1;35m",
        "negative": "\033[1;31m",
        "muted": "\033[2;34m",
        "reset": "\033[0m",
    },
    "sunset": {
        "heading": "\033[1;33m",
        "positive": "\033[1;32m",
        "warning": "\033[1;31m",
        "negative": "\033[1;35m",
        "muted": "\033[2;33m",
        "reset": "\033[0m",
    },
    "forest": {
        "heading": "\033[1;32m",
        "positive": "\033[1;37m",
        "warning": "\033[1;33m",
        "negative": "\033[1;31m",
        "muted": "\033[2;32m",
        "reset": "\033[0m",
    },
}


def render_report(
    store: HabitStore, theme: str = "default", today: date | None = None
) -> list:
    """Render the report as colored lines, one per habit plus a summary."""
    colors = COLOR_THEMES.get(theme, COLOR_THEMES["default"])
    today = today or date.today()
    habits = store.list_habits()
    if not habits:
        return [
            f"{colors['muted']}No habits yet. Add one with 'streak add'.{colors['reset']}"
        ]

    lines = [f"{colors['heading']}Habit report{colors['reset']}"]
    for habit in habits:
        streak = compute_streak(habit["completions"], today)
        if streak:
            status = f"{colors['positive']}{streak} day streak{colors['reset']}"
        else:
            status = f"{colors['warning']}not started today{colors['reset']}"
        lines.append(f"{habit['name']}: {status}")
    lines.append(f"{colors['muted']}Total habits: {len(habits)}{colors['reset']}")
    return lines
''',
            "streak/cli.py": '''"""Command-line interface for streak."""

from datetime import date

import click
import platformdirs

from streak.reminders import ReminderScheduler
from streak.report import render_report
from streak.storage import HabitStore, StorageError


def _data_file():
    return platformdirs.user_data_dir("streak") / "habits.json"


def _load_store() -> HabitStore:
    return HabitStore(_data_file())


@click.group()
def main():
    """streak — a command-line habit tracker."""


@main.command()
@click.argument("name")
@click.option(
    "--daily", "frequency", flag_value="daily", default=True, help="Repeat every day."
)
@click.option(
    "--weekly", "frequency", flag_value="weekly", help="Repeat once a week."
)
def add(name, frequency):
    """Add a new habit with the given NAME."""
    try:
        habit = _load_store().add_habit(name, frequency)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Added habit {habit['name']!r} ({habit['frequency']}).")


@main.command()
@click.argument("name")
def check(name):
    """Mark NAME as completed today."""
    try:
        _load_store().check_in(name, date.today())
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Checked {name!r} for today.")


@main.command()
def list():
    """List all habits with their frequency."""
    store = _load_store()
    for habit in store.list_habits():
        click.echo(f"- {habit['name']} ({habit['frequency']})")


@main.command()
@click.option(
    "--theme",
    default="default",
    show_default=True,
    help="Color theme for the report: default, ocean, sunset, or forest.",
)
def report(theme):
    """Print a report of your habit progress."""
    for line in render_report(_load_store(), theme):
        click.echo(line)


@main.command()
@click.option(
    "--interval",
    "interval_minutes",
    default=None,
    help="Minutes between reminder checks. Defaults to the configured value.",
)
def daemon(interval_minutes):
    """Run in the background and send desktop reminders."""
    ReminderScheduler(_load_store(), interval_minutes).run_forever()
''',
        },
    },
    {
        "message": "Write the habit database atomically",
        "date": "2024-02-01T13:30:00+00:00",
        "files": {
            "streak/storage.py": '''"""JSON file storage for habits and their completion history."""

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path


class StorageError(Exception):
    """Raised when the habit database cannot be read or written."""


class HabitStore:
    """Loads and saves the habit database as a single JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"habits": {}, "settings": {}}
        self.load()

    def load(self):
        """Read the database from disk. A missing file stays empty."""
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as file:
                stored = json.load(file)
        except (json.JSONDecodeError, OSError) as error:
            raise StorageError(f"cannot read {self.path}: {error}") from error
        self.data["habits"] = stored.get("habits", {})
        self.data["settings"] = stored.get("settings", {})

    def save(self):
        """Write the database atomically so a crash cannot corrupt it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix="habits-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(self.data, file, indent=2, sort_keys=True)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def add_habit(self, name: str, frequency: str = "daily") -> dict:
        """Create a new habit and return it."""
        if name in self.data["habits"]:
            raise StorageError(f"habit {name!r} already exists")
        habit = {
            "name": name,
            "frequency": frequency,
            "created": date.today().isoformat(),
            "completions": [],
            "reminder_time": None,
        }
        self.data["habits"][name] = habit
        self.save()
        return habit

    def get_habit(self, name: str) -> dict:
        try:
            return self.data["habits"][name]
        except KeyError as error:
            raise StorageError(f"unknown habit {name!r}") from error

    def delete_habit(self, name: str):
        """Remove a habit and its whole history."""
        if name not in self.data["habits"]:
            raise StorageError(f"unknown habit {name!r}")
        del self.data["habits"][name]
        self.save()

    def check_in(self, name: str, day: date):
        """Record a completion for a habit on the given day."""
        habit = self.get_habit(name)
        day_text = day.isoformat()
        if day_text in habit["completions"]:
            raise StorageError(f"habit {name!r} was already checked on {day_text}")
        habit["completions"].append(day_text)
        self.save()

    def set_reminder(self, name: str, reminder_time: str | None):
        """Configure the daily reminder time for a habit."""
        habit = self.get_habit(name)
        habit["reminder_time"] = reminder_time
        self.save()

    def set_setting(self, key: str, value):
        """Store a configuration value in the database."""
        self.data["settings"][key] = value
        self.save()

    def get_setting(self, key: str, default=None):
        """Read a configuration value, falling back to default."""
        return self.data["settings"].get(key, default)

    def list_habits(self) -> list:
        """Return all habits sorted by name."""
        return sorted(self.data["habits"].values(), key=lambda habit: habit["name"])


def compute_streak(completions: list, today: date) -> int:
    """Return how many consecutive days a habit was completed up to today."""
    completed = set(completions)
    streak = 0
    day = today
    while day.isoformat() in completed:
        streak += 1
        day -= timedelta(days=1)
    return streak
''',
        },
    },
    {
        "message": "Handle local timezones when scheduling reminders",
        "date": "2024-02-04T17:05:00+00:00",
        "files": {
            "streak/reminders.py": '''"""Schedules desktop reminders for habits that are due today."""

import subprocess
import time
from datetime import datetime, time as clock_time

from streak.storage import HabitStore

DEFAULT_INTERVAL_MINUTES = 15


class ReminderScheduler:
    """Periodically checks for due habits and raises desktop notifications."""

    def __init__(self, store: HabitStore, interval_minutes: int | None = None):
        self.store = store
        self.interval_minutes = interval_minutes or store.get_setting(
            "reminder_interval", DEFAULT_INTERVAL_MINUTES
        )

    def run_forever(self):
        """Check for due habits every interval until interrupted."""
        while True:
            self.check_due_habits()
            time.sleep(self.interval_minutes * 60)

    def check_due_habits(self):
        """Notify the user about every habit whose local reminder time passed."""
        now = datetime.now().astimezone().timetz()
        for habit in self.store.list_habits():
            if self._is_due(habit, now):
                self._notify(habit)

    def _is_due(self, habit: dict, now: clock_time) -> bool:
        """A habit is due when a reminder time is set and has already passed."""
        reminder = habit.get("reminder_time")
        if not reminder:
            return False
        hour, minute = (int(part) for part in reminder.split(":"))
        return clock_time(hour, minute, tzinfo=now.tzinfo) <= now

    def _notify(self, habit: dict):
        """Show a desktop notification using notify-send."""
        title = "Habit reminder"
        message = f"Remember to complete your habit: {habit['name']}"
        subprocess.run(
            ["notify-send", "--app-name=streak", title, message],
            check=False,
        )
''',
        },
    },
    {
        "message": "Add a monthly summary section to the report",
        "date": "2024-02-08T10:25:00+00:00",
        "files": {
            "streak/report.py": r'''"""Renders a colored terminal report of habit progress."""

from collections import Counter
from datetime import date

from streak.storage import HabitStore, compute_streak

# Color themes map semantic roles to ANSI escape codes. Users can pick one
# with the --theme option of the report command.
COLOR_THEMES = {
    "default": {
        "heading": "\033[1;37m",
        "positive": "\033[1;32m",
        "warning": "\033[1;33m",
        "negative": "\033[1;31m",
        "muted": "\033[2m",
        "reset": "\033[0m",
    },
    "ocean": {
        "heading": "\033[1;36m",
        "positive": "\033[1;34m",
        "warning": "\033[1;35m",
        "negative": "\033[1;31m",
        "muted": "\033[2;34m",
        "reset": "\033[0m",
    },
    "sunset": {
        "heading": "\033[1;33m",
        "positive": "\033[1;32m",
        "warning": "\033[1;31m",
        "negative": "\033[1;35m",
        "muted": "\033[2;33m",
        "reset": "\033[0m",
    },
    "forest": {
        "heading": "\033[1;32m",
        "positive": "\033[1;37m",
        "warning": "\033[1;33m",
        "negative": "\033[1;31m",
        "muted": "\033[2;32m",
        "reset": "\033[0m",
    },
}


def render_report(
    store: HabitStore, theme: str = "default", today: date | None = None
) -> list:
    """Render the report as colored lines, one per habit plus a summary."""
    colors = COLOR_THEMES.get(theme, COLOR_THEMES["default"])
    today = today or date.today()
    habits = store.list_habits()
    if not habits:
        return [
            f"{colors['muted']}No habits yet. Add one with 'streak add'.{colors['reset']}"
        ]

    lines = [f"{colors['heading']}Habit report{colors['reset']}"]
    for habit in habits:
        streak = compute_streak(habit["completions"], today)
        if streak:
            status = f"{colors['positive']}{streak} day streak{colors['reset']}"
        else:
            status = f"{colors['warning']}not started today{colors['reset']}"
        lines.append(f"{habit['name']}: {status}")
    lines.extend(_monthly_summary(habits, today, colors))
    lines.append(f"{colors['muted']}Total habits: {len(habits)}{colors['reset']}")
    return lines


def _monthly_summary(habits: list, today: date, colors: dict) -> list:
    """Return a few lines summarizing completions in the current month."""
    month_prefix = today.strftime("%Y-%m")
    completions = Counter()
    for habit in habits:
        for day in habit["completions"]:
            if day.startswith(month_prefix):
                completions[habit["name"]] += 1

    lines = [f"{colors['heading']}This month{colors['reset']}"]
    if not completions:
        lines.append(f"{colors['muted']}No completions yet this month.{colors['reset']}")
        return lines
    for name, count in completions.most_common():
        lines.append(f"{colors['positive']}{name}: {count} check-ins{colors['reset']}")
    return lines
''',
        },
    },
    {
        "message": "Document installation for Arch Linux and other distributions",
        "date": "2024-02-12T11:40:00+00:00",
        "files": {
            "README.md": """# streak — a command-line habit tracker

streak is a small command-line habit tracker written in Python. It keeps your
habits in a local JSON database, tracks your streaks, and prints a colored
report so you can see your progress at a glance.

## Features

- Add, list, check, and delete habits from the terminal
- Automatic streak and best-streak tracking
- A colored terminal report with configurable color themes
- Desktop reminders for habits that are due
- Works fully offline; your data never leaves your machine

## Installation

### Arch Linux

Installation instructions for Arch Linux:

streak is available in the Arch User Repository as the `streak` package:

```sh
yay -S streak
```

### Debian and Ubuntu

Install the `.deb` package from the [releases page](https://example.com/releases)
or with apt from the streak apt repository:

```sh
sudo apt install streak
```

### Fedora

Install from the COPR repository:

```sh
sudo dnf copr enable example/streak
sudo dnf install streak
```

### From source

Clone the repository and install with pip:

```sh
git clone https://example.com/streak.git
cd streak
pip install .
```

## Usage

Start by adding a habit:

```sh
streak add "drink two liters of water" --daily
```

Mark a habit as done for today:

```sh
streak check "drink two liters of water"
```

List all habits with their current streaks:

```sh
streak list
```

### The report

The `streak report` command prints a colored overview of your habits:

```sh
streak report
```

## Configuration

streak stores its data in `~/.local/share/streak/habits.json`. The report
colors and other options live in `~/.config/streak/config.toml`.

## License

MIT
""",
            "pyproject.toml": """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "streak"
version = "2.1.0"
description = "A command-line habit tracker with colored reports and desktop reminders"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "Test Author", email = "test@example.com" }]
dependencies = [
    "click>=8.1,<9",
    "platformdirs>=4,<5",
]

[project.scripts]
streak = "streak.cli:main"

[project.optional-dependencies]
notify = ["dbus-next>=0.2,<1"]

[tool.setuptools]
packages = ["streak"]
""",
            "streak/__init__.py": '''"""streak — a command-line habit tracker."""

__version__ = "2.1.0"
''',
        },
    },
    {
        "message": "Add a pastel color theme to the report",
        "branch": "color-themes",
        "date": "2024-02-15T19:20:00+00:00",
        "files": {
            "streak/report.py": r'''"""Renders a colored terminal report of habit progress."""

from collections import Counter
from datetime import date

from streak.storage import HabitStore, compute_streak

# Color themes map semantic roles to ANSI escape codes. Users can pick one
# with the --theme option of the report command.
COLOR_THEMES = {
    "default": {
        "heading": "\033[1;37m",
        "positive": "\033[1;32m",
        "warning": "\033[1;33m",
        "negative": "\033[1;31m",
        "muted": "\033[2m",
        "reset": "\033[0m",
    },
    "ocean": {
        "heading": "\033[1;36m",
        "positive": "\033[1;34m",
        "warning": "\033[1;35m",
        "negative": "\033[1;31m",
        "muted": "\033[2;34m",
        "reset": "\033[0m",
    },
    "sunset": {
        "heading": "\033[1;33m",
        "positive": "\033[1;32m",
        "warning": "\033[1;31m",
        "negative": "\033[1;35m",
        "muted": "\033[2;33m",
        "reset": "\033[0m",
    },
    "forest": {
        "heading": "\033[1;32m",
        "positive": "\033[1;37m",
        "warning": "\033[1;33m",
        "negative": "\033[1;31m",
        "muted": "\033[2;32m",
        "reset": "\033[0m",
    },
    "pastel": {
        "heading": "\033[1;38;5;219m",
        "positive": "\033[38;5;114m",
        "warning": "\033[38;5;222m",
        "negative": "\033[38;5;203m",
        "muted": "\033[2;38;5;145m",
        "reset": "\033[0m",
    },
}


def render_report(
    store: HabitStore, theme: str = "default", today: date | None = None
) -> list:
    """Render the report as colored lines, one per habit plus a summary."""
    colors = COLOR_THEMES.get(theme, COLOR_THEMES["default"])
    today = today or date.today()
    habits = store.list_habits()
    if not habits:
        return [
            f"{colors['muted']}No habits yet. Add one with 'streak add'.{colors['reset']}"
        ]

    lines = [f"{colors['heading']}Habit report{colors['reset']}"]
    for habit in habits:
        streak = compute_streak(habit["completions"], today)
        if streak:
            status = f"{colors['positive']}{streak} day streak{colors['reset']}"
        else:
            status = f"{colors['warning']}not started today{colors['reset']}"
        lines.append(f"{habit['name']}: {status}")
    lines.extend(_monthly_summary(habits, today, colors))
    lines.append(f"{colors['muted']}Total habits: {len(habits)}{colors['reset']}")
    return lines


def _monthly_summary(habits: list, today: date, colors: dict) -> list:
    """Return a few lines summarizing completions in the current month."""
    month_prefix = today.strftime("%Y-%m")
    completions = Counter()
    for habit in habits:
        for day in habit["completions"]:
            if day.startswith(month_prefix):
                completions[habit["name"]] += 1

    lines = [f"{colors['heading']}This month{colors['reset']}"]
    if not completions:
        lines.append(f"{colors['muted']}No completions yet this month.{colors['reset']}")
        return lines
    for name, count in completions.most_common():
        lines.append(f"{colors['positive']}{name}: {count} check-ins{colors['reset']}")
    return lines
''',
        },
    },
    {
        "message": "Merge branch 'color-themes'",
        "merge": "color-themes",
        "date": "2024-02-16T09:10:00+00:00",
    },
    {
        "message": "Expand the usage examples in the README",
        "date": "2024-02-19T14:50:00+00:00",
        "files": {
            "README.md": """# streak — a command-line habit tracker

streak is a small command-line habit tracker written in Python. It keeps your
habits in a local JSON database, tracks your streaks, and prints a colored
report so you can see your progress at a glance.

## Features

- Add, list, check, and delete habits from the terminal
- Automatic streak and best-streak tracking
- A colored terminal report with configurable color themes
- Desktop reminders for habits that are due
- Works fully offline; your data never leaves your machine

## Installation

### Arch Linux

Installation instructions for Arch Linux:

streak is available in the Arch User Repository as the `streak` package:

```sh
yay -S streak
```

### Debian and Ubuntu

Install the `.deb` package from the [releases page](https://example.com/releases)
or with apt from the streak apt repository:

```sh
sudo apt install streak
```

### Fedora

Install from the COPR repository:

```sh
sudo dnf copr enable example/streak
sudo dnf install streak
```

### From source

Clone the repository and install with pip:

```sh
git clone https://example.com/streak.git
cd streak
pip install .
```

## Usage

Start by adding a habit:

```sh
streak add "drink two liters of water" --daily
```

Mark a habit as done for today:

```sh
streak check "drink two liters of water"
```

List all habits with their current streaks:

```sh
streak list
```

### The report

The `streak report` command prints a colored overview of your habits. Pick a
color theme with `--theme`:

```sh
streak report --theme ocean
```

The available themes are `default`, `ocean`, `sunset`, `forest`, and `pastel`.

### Reminders

Set a daily reminder time for a habit:

```sh
streak remind "drink two liters of water" --at 20:00
```

Then run the background daemon that sends desktop notifications:

```sh
streak daemon --interval 30
```

## Configuration

streak stores its data in `~/.local/share/streak/habits.json`. The report
colors and other options live in `~/.config/streak/config.toml`.

## License

MIT
""",
        },
    },
    {
        "message": "Add delete and export commands",
        "date": "2024-02-23T08:55:00+00:00",
        "files": {
            "streak/cli.py": '''"""Command-line interface for streak."""

import json
from datetime import date
from pathlib import Path

import click
import platformdirs

from streak.reminders import ReminderScheduler
from streak.report import render_report
from streak.storage import HabitStore, StorageError


def _data_file():
    return platformdirs.user_data_dir("streak") / "habits.json"


def _load_store() -> HabitStore:
    return HabitStore(_data_file())


@click.group()
def main():
    """streak — a command-line habit tracker."""


@main.command()
@click.argument("name")
@click.option(
    "--daily", "frequency", flag_value="daily", default=True, help="Repeat every day."
)
@click.option(
    "--weekly", "frequency", flag_value="weekly", help="Repeat once a week."
)
def add(name, frequency):
    """Add a new habit with the given NAME."""
    try:
        habit = _load_store().add_habit(name, frequency)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Added habit {habit['name']!r} ({habit['frequency']}).")


@main.command()
@click.argument("name")
def check(name):
    """Mark NAME as completed today."""
    try:
        _load_store().check_in(name, date.today())
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Checked {name!r} for today.")


@main.command()
@click.argument("name")
def delete(name):
    """Remove NAME and its whole history."""
    try:
        _load_store().delete_habit(name)
    except StorageError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Deleted habit {name!r}.")


@main.command()
def list():
    """List all habits with their frequency."""
    store = _load_store()
    for habit in store.list_habits():
        click.echo(f"- {habit['name']} ({habit['frequency']})")


@main.command()
@click.option(
    "--theme",
    default="default",
    show_default=True,
    help="Color theme for the report: default, ocean, sunset, forest, or pastel.",
)
def report(theme):
    """Print a report of your habit progress."""
    for line in render_report(_load_store(), theme):
        click.echo(line)


@main.command()
@click.option(
    "--interval",
    "interval_minutes",
    default=None,
    help="Minutes between reminder checks. Defaults to the configured value.",
)
def daemon(interval_minutes):
    """Run in the background and send desktop reminders."""
    ReminderScheduler(_load_store(), interval_minutes).run_forever()


@main.command()
@click.argument("output", type=click.Path())
@click.option(
    "--format",
    "format_name",
    type=click.Choice(["json", "csv"]),
    default="json",
    show_default=True,
)
def export(output, format_name):
    """Export all habit data to a JSON or CSV file."""
    store = _load_store()
    if format_name == "csv":
        rows = ["name,frequency,created,reminder_time"]
        for habit in store.list_habits():
            rows.append(
                f"{habit['name']},{habit['frequency']},{habit['created']},"
                f"{habit['reminder_time'] or ''}"
            )
        Path(output).write_text("\n".join(rows) + "\n", encoding="utf-8")
    else:
        Path(output).write_text(
            json.dumps(store.data, indent=2, sort_keys=True), encoding="utf-8"
        )
    click.echo(f"Exported habit data to {output}.")
''',
        },
    },
]
