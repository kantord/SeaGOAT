<!-- markdownlint-disable MD033 -->

<h1>
  <p align="center">
    <img src="branding/logo-small.png" alt="Logo" width="200"/>
    <font size="8"><b>SeaGOAT</b></font>
  </p>
</h1>

A code search engine for the AI age. SeaGOAT leverages vector embeddings to
enable to search your codebase semantically.

## Development

**Requirements**:

* [Poetry](https://python-poetry.org/)
* Python 3.11 or newer
* [ripgrep](https://github.com/BurntSushi/ripgrep)

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

### Manually testing

To manually test this app against a code repository,
you can use the following command:

```bash
poetry run seagoat ~/path/to/your/repository
```
