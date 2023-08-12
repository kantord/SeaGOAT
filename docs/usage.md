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

#### Using Regular Expressions

One of SeaGOAT's most powerful features is the ability to combine regular expressions
with AI-driven vector queries. This synergistic approach narrows down your
codebase search using pattern-based regular expressions while leveraging AI
to understand the semantic meaning behind your query.

```bash
seagoat "function db_.* that initializes database"
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

Note that the line number limit is only applied to actual result lines.
If you include context lines, those lines will not be counted as part of the
limit and will be displayed regardless. When the last last result line of the
last result file is displayed, all following context lines until the next
result line (or the end of the file) are displayed.

### `--version`: Print version number

This prints the version of your current SeaGOAT installation.

### `-B, --context-above`: Lines of context before each result

This option allows you to include a specified number of lines
of context before each matching result.

!!! note "Tricky context lines"

    Context lines are lines that are added because they are adjacent to a
    result line.

    That being said, because lines are grouped into chunks of 3,
    results based on vector embeddings might already contain lines that might
    not be strictly related to the query.

    This might make it appear like there are more context lines than you
    requested. Consider this when deciding how many context lines to include.

```bash title="Example"
seagoat "myQuery" --context-above=5
```

### `-A, --context-below`: Lines of context after each result

This option allows you to include a specified number of lines of context after
each matching result.

```bash title="Example"
seagoat "myQuery" --context-below=5
```

!!! note "Tricky context lines"

    Context lines are lines that are added because they are adjacent to a
    result line.

    That being said, because lines are grouped into chunks of 3,
    results based on vector embeddings might already contain lines that might
    not be strictly related to the query.

    This might make it appear like there are more context lines than you
    requested. Consider this when deciding how many context lines to include.

### `-C, --context`: Lines of context both before and after each result

This option sets both `--context-above` and `--context-below` to the same
specified value. This is useful if you want an equal amount of context around
each matching result.

```bash title="Example"
seagoat "myQuery" --context=5
```

!!! note "Tricky context lines"

    Context lines are lines that are added because they are adjacent to a
    result line.

    That being said, because lines are grouped into chunks of 3,
    results based on vector embeddings might already contain lines that might
    not be strictly related to the query.

    This might make it appear like there are more context lines than you
    requested. Consider this when deciding how many context lines to include.
