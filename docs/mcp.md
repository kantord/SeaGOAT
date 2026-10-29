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

One SeaGOAT server process (an *instance*) serves every repository. If the
instance is already running, starting it for another repository adds that
repository to it, starts indexing it and returns at once. The `search_code`
tool sends the repository path with every query, so one instance can answer
for many repositories. A server reached from another computer must already
have the repository added on the computer running it.

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
