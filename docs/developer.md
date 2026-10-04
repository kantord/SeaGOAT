# Developer documentation

This document was created to help you set up your development environment
and to understand the project structure.

## Setting up the development environment

### Step 1: (Optional) Install SeaGOAT

This step is recommended in order to make sure that SeaGOAT works properly
on your computer.

[Follow the official documentation](index.md#install-seagoat)

### Step 2: Make sure you have all developer dependencies installed

The following dependencies need to be installed:

* [Git](https://git-scm.com/downloads)
* [Python 3.10 or newer](https://www.python.org/downloads/)
* [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Step 3: Clone the repository

Use Git to clone the repository:

```bash
git clone git@github.com:kantord/SeaGOAT.git
cd SeaGOAT
```

### Step 4: Run `uv sync`

uv is used to manage dependencies in this project. uv also manages
virtualenvs automatically.

If you have uv installed correctly, automatically setting up a virtualenv
and installing all dependencies is as easy as running:

```bash
uv sync
```

### Step 5: Run tests

To make sure that your development environment was set up correctly, run
tests:

```bash
uv run pytest
```

If all tests pass, you have set up your development environment correctly.

### Step 6: (Optional) Set up pre-commit hooks

There are several tools in use in SeaGOAT to make sure that code is ready to
merge. Some of these tools will automatically fix issues with the code, such
as reformatting the code to enforce code style. Other tools will merely point
out issues before you commit your code.

It is recommended to set up pre-commit hooks so that these checks are
executed automatically. You can do so by running this command:

```bash
uv run pre-commit install
```

If you do *not* wish to use pre-commit hooks, you can still execute all
checks manually by running:

```bash
uv run pre-commit run --all-files
```

## Developing SeaGOAT

### Automated testing

Automated testing is done using `pytest`. Here are some example use cases:

#### Watch mode

Automatically runs tests for **all** files when you save your changes:

```bash
uv run ptw
```

#### Test changed files

```bash
uv run pytest . --testmon
```

#### Test all files

```bash
uv run pytest .
```

#### Snapshot testing

Snapshot testing is used in a few test cases.
You can update snapshots by running

```bash
uv run pytest  --snapshot-update
```

### Manual testing

In order to test your local changes to SeaGOAT manually, you can prefix
the command by `uv run`. For example to run your local
version of `seagoat-server`, just run:

```bash
uv run seagoat-server
```

Similarly, to run your local version of `gt`/`seagoat`, you can run:

```bash
uv run gt
```

You can run an `ipython` in the correct virtualenv also by prefixing it
with `uv run`:

```bash
uv run ipython
```

### Automatic checks (linting) and automatic formatting

This repository uses `pre-commit` to run automatic checks and fixes on the
codebase in addition to automatic and manual testing.

If you have
[set up commit hooks](http://localhost:8000/developer/#step-6-optional-set-up-pre-commit-hooks)
(recommended), then these checks and fixes are automatically executed
each time you attempt to make a commit.

If you don't like commit hooks, or *if you want to run the checks for all
files, not just changed files* then you can run the following command:

```bash
pre-commit run --all-files
```

{!../CONTRIBUTING.md!}
