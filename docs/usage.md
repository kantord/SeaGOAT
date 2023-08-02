# Usage

SeaGOAT is a command-line tool designed to assist in querying your codebase.
By using technologies such as ChromaDB and ripgrep, it goes beyond direct
match searches and uses semantic meaning to quickly find
details related to your query.

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

## Options

* `--no-color`: If used, it disables formatting in the output.
This is automatically enabled when used as part of a bash pipeline.

* `-l, --max-results`: This option allows you to limit the number of
result lines. It is an integer type option.

* `--version`: If used, it displays the version of the seagoat program.

## Examples

### Query current folder

```bash
seagoat "myQuery"
```

### Query specific folder

```bash
seagoat "myQuery" "/path/to/my/repo"
```

### Limit number of result lines

```bash
seagoat "myQuery" --max-results=5
```

### Disable syntax highlighting

```bash
seagoat "myQuery" --no-color
```
