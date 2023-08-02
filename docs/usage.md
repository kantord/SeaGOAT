<!-- markdownlint-disable MD046 -->
# Usage

SeaGOAT is a command-line tool designed to assist in querying your codebase.
By using technologies such as ChromaDB and ripgrep, it goes beyond direct
match searches and uses semantic meaning to quickly find
details related to your query.

!!! info "Only works with Git"

    SeaGOAT takes your Git history into account in order to provide
    the most useful and relevant results.

## Command Usage

```bash
seagoat <query> [repo_path] [OPTIONS]
```

!!! note
    The seagoat CLI queries the SeaGOAT server. If the server is not running,
    you would be prompted to start the server using
    `seagoat-server start {repo_path} command`.

## Arguments

* `query`: This is a required argument.
It is the query to be made to the SeaGOAT server.
* `repo_path`: This argument is optional, and defaults
to the current working directory. It represents the path to the code repository.

### Examples

#### Query current folder

```bash
seagoat "myQuery"
```

#### Query specific folder

```bash
seagoat "myQuery" "/path/to/my/repo"
```

## Options

### `--no-color`: Disable syntax highlighting

This is automatically enabled when used as part of a bash pipeline.

```bash title="Example"
seagoat "myQuery" --no-color
```

### `-l, --max-results`: Limit number of results

This limits the number of result lines displayed.
Useful if you only care about the best results.

```bash title="Example"
seagoat "myQuery" --max-results=5
```

### `--version`: Print version number

This prints the version of your current SeaGOAT installation.
