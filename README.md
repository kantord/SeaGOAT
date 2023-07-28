<!-- markdownlint-disable MD033 -->

<h1>
  <p align="center">
    <img src="assets/logo-small.png" alt="Logo" width="200"/>
    <font size="8"><b>SeaGOAT</b></font>
  </p>
</h1>

A code search engine for the AI age. SeaGOAT leverages vector
embeddings to enable to search your codebase semantically.

## Getting started

### Install SeaGOAT

In order to install SeaGOAT, you need to have the following
dependencies already installed on your computer:

- Python 3.11 or newer
- ripgrep

To install SeaGOAT using `pip`, use the following command:

```bash
pip install seagoat
```

### Start SeaGOAT server

In order to use SeaGOAT in your project, you have to start the SeaGOAT server
using the following command:

```bash
seagoat-server start /path/to/your/repo
```

### Search your repository

If you have the server running, you can simply use the
`gt` or `seagoat` command to query your repository. For example:

```bash
gt "Where are the numbers rounded"
```

### Stopping the server

You can stop the running server using the following command:

```bash
seagoat-server stop /path/to/your/repo
```

## Development

**Requirements**:

- [Poetry](https://python-poetry.org/)
- Python 3.11 or newer
- [ripgrep](https://github.com/BurntSushi/ripgrep)

### Install dependencies

After cloning the repository, install dependencies using the following command:

```bash
poetry install
```

### Running tests

#### Watch mode (recommended)

```bash
poetry run ptw
```

#### Test changed files

```bash
poetry run pytest .  --testmon
```

#### Test all files

```bash
poetry run pytest .
```

### Manual testing

You can test any SeaGOAT command manually in your local development
environment. For example to test the development version of the
`seagoat-server` command, you can run:

```bash
poetry run seagoat-server ~/path/an/example/repository
```
