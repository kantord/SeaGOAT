# SeaGOAT MCP Server

SeaGOAT includes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
server that allows AI assistants (like Claude Desktop) to search your local
codebase utilizing SeaGOAT's semantic search engine.

## Prerequisites

1. You must have SeaGOAT installed (`pipx install seagoat`).
2. You must have the SeaGOAT background server running for the repository you want
   to search.

```bash
seagoat-server start /path/to/your/repository
```

One SeaGOAT server process (an *instance*) serves the repositories listed in
the `repositories.json` file next to the instance file in SeaGOAT's cache
directory (for example `~/.cache/seagoat-servers/repositories.json` on
Linux). `seagoat-server start <repo>` writes `<repo>` into that file, starts
the instance if none is running, and otherwise tells the running instance to
load it. Removing a repository from the list takes effect when the instance
restarts; a repository's own `.seagoat.yml` cannot set it. The `search_code`
tool sends the repository path with every query, so any program that can
reach the server can query the repositories it serves. A query naming a
repository the instance does not serve gets an HTTP 404 error saying so.

## Configuration

To use SeaGOAT with Claude Desktop, add the following configuration to your
`claude_desktop_config.json` file.

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

### Using pipx (Recommended)

If you installed SeaGOAT via `pipx`, the `seagoat-mcp` command should be
available globally.

```json
{
  "mcpServers": {
    "seagoat": {
      "command": "seagoat-mcp",
      "args": []
    }
  }
}
```

### Using a Manual Path

If the above doesn't work, point directly to the executable.

```json
{
  "mcpServers": {
    "seagoat": {
      "command": "/Users/username/.local/pipx/venvs/seagoat/bin/seagoat-mcp",
      "args": []
    }
  }
}
```

## Usage

Once configured, simply restart Claude Desktop. You should see a small plug icon
indicating the server is connected.

You can then ask Claude questions like:

> "Search my codebase for the login authentication logic"
>
> "Find code related to data processing in `src/utils`"

Claude will use the `search_code` tool to query your local SeaGOAT server and
retrieve relevant code snippets to answer your question. The tool's
`repo_path` argument tells the instance which repository to search; the
MCP server sends it with every query.
