<!-- markdownlint-disable MD046 -->
<!-- markdownlint-disable MD036 -->
# SeaGOAT-server

The `seagoat-server` is an integral component of the Seagoat command-line tool
designed to analyze your codebase and create vector embeddings for it.

While it serves as a backend for the command-line tool, also allows you to
use it through HTTP to build your own SeaGOAT-based applications.

## Starting the server

To boot up the server for a specific repository, use:

```bash
seagoat-server start <repo_path> [--port=<custom_port>]
```

* `repo_path` - Path to your Git repository.
* `--port` - (Optional) Run the server on a specific port.

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
    "globalCache": "/home/myuser/.cache/seagoat",
    "globalConfigFile": "/home/myuser/.config/seagoat/config.yml",
    "servers": {
        "/path/to/repository/1": {
            "cacheLocation": {
              "chroma": "/home/myuser/.cache/seagoat/bfe8133b9e871ea1c8498a0"
            },
            "isRunning": true,
            "host": "127.0.0.1",
            "port": "8080",
            "address": "http://127.0.0.1:8080"
        },
        "/path/to/repository/2": {
            "cacheLocation": {
              "chroma": "/home/myuser/.cache/seagoat/fbee39c83bd47a75e2f839"
            },
            "isRunning": false,
            "host": "127.0.0.1",
            "port": "8081",
            "address": "http://127.0.0.1:8081"
        }
    }
}
```

In this output, you can also see information about where databases/caches
related to your projects are stored. `globalCache` is the parent folder of
all the cache directories, and within each server, you can find an attribute
called `cacheLocation` which contains the path to the cache directory for
each different type of cache associated with that project.

If you want to create a configuration file, you can see the path for it
in the `globalConfigFile` attribute. This depends on your operating system.
You can also create a configuration file for your project. See
[the configuration documentation](configuration.md) for more information.

### Querying code lines using the API

If you want to build an application using SeaGOAT-server, first you need to
figure out the address of the server you want to connect to.

To find the address of each SeaGOAT-server running on
your computer, use `seagoat-server server-info`. See the explanation above.

**Example query**

Once you have the address, you can start making queries to it. For instance,
this is how you'd make a query using `curl` to the server running on
`http://localhost:32835`:

```bash
curl -X POST 'http://localhost:34743/lines/query' \
-H 'Content-Type: application/json' \
-d '{
      "queryText": "your_query_here",
      "limitClue": "500",
      "contextAbove": 3,
      "contextBelow": 3
    }'
```

**Payload structure**

* `queryText` - The actual text of your query.
* `limitClue` - This number should indicate how many results you are
planning to display. This is not a hard limit, you might receive
more data than what you asked for. Nevertheless, you might not receive
enough results if your limit clue is low.
* `contextAbove` - Number of context lines above each result line
* `contextBelow` - Number of context lines below each result line

**Example response**

You will receive a response similar to this one:

```json
{
  "results": [
    {
      "path": "tests/conftest.py",
      "fullPath": "/home/user/repos/SeaGOAT/tests/conftest.py",
      "score": 0.6,
      "blocks": [
        {
          "score": 0.21,
          "lines": [
            {
              "score": 0.21,
              "line": 100,
              "lineText": "def very_relevant_function():",
              "resultTypes": [
                "result"
              ]
            }
          ],
          "lineTypeCount": {
            "result": 1
          }
        },
        {
          "score": 0.6,
          "lines": [
            {
              "score": 0.6,
              "line": 489,
              "lineText": " contents=(\"hello()\\n\" * (i % 50)),",
              "resultTypes": [
                "result"
              ]
            },
            {
              "score": 0.84,
              "line": 490,
              "lineText": "     return foo * bar",
              "resultTypes": [
                "result"
              ]
            }
          ],
          "lineTypeCount": {
            "result": 1
          }
        }
      ]
    },
    {
      "path": "tests/test_cli.py",
      "fullPath": "/home/user/repos/SeaGOAT/tests/test_cli.py",
      "score": 0.87,
      "blocks": [... etc ... ]
    },
    ... etc ...
  ],
  "version": "0.26.0"
}
```

**Understanding the response**

The response contains the following information:

* `version` - This is the version of SeaGOAT being used.
* `results` - This is an array containing your results.

Each result inside results has the following data:

* `path` - The (relative) path of the file within the repository.
* `fullPath` - The absolute path to the file in your filesystem.
* `score` - A number indicating how relevant a result is, smaller is better.
* `blocks` - An array of relevant code blocks from this file.

Within each block you will find:

* `lines` - An array of line objects containing:
  * `score` - Relevance score for this line. See `score` above.
  * `line` - The line number in the file where the result was found.
  * `lineText` - The actual text content of that line.
  * `resultTypes` - An array indicating all types of result on this line:
    * `"result"` Means that the line is directly relevant to the query.
    * `"context"` Means that the line was added as a context line.
    * `"bridge"` It is a type of context line that is added within a block
    rather than around it. It is used to merge code blocks when they are
    nearly touching.
* `lineTypeCount` - An object containing a count of all line types within
  the code block. See `resultTypes` for more.
* `score` - A score for the code block overall.

### Querying code files using the API

There is another endpoint that is specifically designed to find code files
instead of finding specific lines or code blocks.

**Example query**

Once you have the address, you can start making queries to it. For instance,
this is how you'd make a query using `curl` to the server running on
`http://localhost:32835`:

```bash
curl -X POST 'http://localhost:34743/files/query' \
-H 'Content-Type: application/json' \
-d '{
  "queryText": "your_query_here",
  "limitClue": "500",
}'
```

**Payload structure**

* `queryText` - The actual text of your query.
* `limitClue` - This number should indicate how many results you are
planning to display. This is not a hard limit, you might receive
more data than what you asked for. Nevertheless, you might not receive
enough results if your limit clue is low. When querying files
instead of lines, the limit clue is more tricky because the limit
is still expressed in number of lines, but the results are files.

**Example response**

You will receive a response similar to this one:

```json
{
    "results": [
        {
            "fullPath": "tests/conftest.py",
            "path": "tests/conftest.py"
        },
        {
            "fullPath": "tests/test_cli.py",
            "path": "tests/test_cli.py"
        },
        {
            "fullPath": "tests/test_result.py",
            "path": "tests/test_result.py"
        },
        {
            "fullPath": "tests/test_file.py",
            "path": "tests/test_file.py"
        },
        {
            "fullPath": "tests/test_repository.py",
            "path": "tests/test_repository.py"
        },
        {
            "fullPath": "tests/test_source_ripgrep.py",
            "path": "tests/test_source_ripgrep.py"
        },
        {
            "fullPath": "docs/server.md",
            "path": "docs/server.md"
        }
    ],
    "version": "0.43.0"
}
```
