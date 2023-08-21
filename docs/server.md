<!-- markdownlint-disable MD046 -->
# SeaGOAT-server

The seagoat-server is an integral component of the Seagoat command-line tool
designed to analyze your codebase and create vector embeddings for it.

While it serves as a backend for the command-line tool, also allows you to
use it through HTTP to build your own SeaGOAT-based applications.

## Starting the server

To boot up the server for a specific repository, use:

```bash
seagoat-server start <repo_path> [--port=<custom_port>]
```

* `repo_path`: Path to your Git repository
* `--port`: (Optional) Run the server on a specific port

If you don't specify a custom port, a random port will be assigned to your
server. Don't worry, SeaGOAT will still be able to automatically find
the server corresponding to a specific repository.
