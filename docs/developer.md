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

* Git
* Python 3.11 or newer
* Poetry ([how to install](https://python-poetry.org/docs/#installation))

### Step 3: Clone the repository

Use Git to close the repository:

```bash
git clone git@github.com:kantord/SeaGOAT.git
cd SeaGOAT
```

### Step 4: Run `poetry install`

Poetry is used to manage dependencies in this project. Poetry also manages
virtualenvs automatically.

If you have Poetry installed correctly, automatically setting up a virtualenv
and installing all dependencies is as easy as running:

```bash
poetry install
```

### Step 5: Run tests

To make sure that your development environment was set up correctly, run
tests:

```bash
poetry run pytest
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
pre-commit install
```

If you do *not* wish to use pre-commit hooks, you can still execute all
checks manually by running:

```bash
pre-commit run --all-files
```

## Developing SeaGOAT

### Automated testing

Automated testing is done using `pytest`. Here are some example use cases:

#### Watch mode

Automatically runs tests for **all** files when you save your changes:

```bash
poetry run ptw
```

#### Test changed files

```bash
poetry run pytest . --testmon
```

#### Test all files

```bash
poetry run pytest .
```

#### Snapshot testing

Snapshot testing is used in a few test cases.
You can update snapshots by running

```bash
poetry run pytest  --snapshot-update
```

### Manual testing

In order to test your local changes to SeaGOAT manually, you can prefix
the command by `poetry run`. For example to run your local
version of `seagoat-server`, just run:

```bash
poetry run seagoat-server
```

Similarly, to run your local version of `gt`/`seagoat`, you can run:

```bash
poetry run gt
```

You can run an `ipython` in the correct virtualenv also by prefixing it
with `poetry run`:

```bash
poetry run ipython
```

## Contributing to SeaGOAT

Welcome to SeaGOAT!

We value your contributions and ask you to please adhere to
our
[Code of Conduct](https://github.com/kantord/SeaGOAT/blob/main/CODE_OF_CONDUCT.md)
and follow these brief guidelines.

### Getting Started

* Follow the
  [guide on how set up the development environment](https://kantord.github.io/SeaGOAT/latest/developer/#setting-up-the-development-environment)
* Look for issues labeled
  [`up for grabs`](https://github.com/kantord/SeaGOAT/issues?q=is%3Aopen+is%3Aissue+label%3A%22up+for+grabs%22)
  or
  [`good first issue`](https://github.com/kantord/SeaGOAT/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)
  as starting points.
* Report bugs or suggest enhancements by
  [creating an issue](https://github.com/kantord/SeaGOAT/issues/new)
  with the `bug` or `enhancement` label.

### Contribution Process

1. **Fork & Create a Branch:**
   [Fork the repo](https://docs.github.com/en/get-started/quickstart/fork-a-repo)
   and create a branch with a descriptive name in your fork.
2. **Develop & Test Changes:** Make and test your changes, adhering to existing
   coding standards. If you have configured your development environment
   correctly, automated tools will help you with this.
3. **Submit a Pull Request:**
   [Open a Pull Request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request)
   targeting the `main` branch of the original repo.
4. **Address Review Comments:** After you submitted a pull request, it will
   be reviewed by a maintainer as soon as possible. In order to make sure
   your changes get merged, you have to address any comments in your pull
   request until it is finally approved. After your changes are approved and
   merged, they will be released automatically if there are any user facing
   changes.
