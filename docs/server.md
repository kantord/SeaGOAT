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

## Developing with SeaGOAT-server

SeaGOAT-server not only serves as a backend for the SeaGOAT command-line tool
but also offers developers the capability to integrate its functions to build
custom applications.

### Retrieving server information

As SeaGOAT servers only run on one repository at a time, there is a command
provided in order to gather information about all running servers, including
how to access them through HTTP.

To get detailed information about all active SeaGOAT servers in JSON format,
you can utilize the `server-info` command:

```bash
seagoat-server server-info
```

You will receive a response similar to this:

```json
{
    "version": "0.5.3",
    "servers": {
        "/path/to/repository/1": {
            "host": "127.0.0.1",
            "port": "8080",
            "address": "http://127.0.0.1:8080"
        },
        "/path/to/repository/1": {
            "host": "127.0.0.1",
            "port": "8081",
            "address": "http://127.0.0.1:8081"
        }
    }
}
```
