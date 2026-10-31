"""
MCP Server implementation for SeaGOAT.
"""

import os

import requests
from mcp.server.mcpserver import MCPServer

from seagoat import __version__
from seagoat.projects import resolve_repo_path
from seagoat.utils.server import (
    instance_url,
    normalize_repo_path,
    running_instance,
)

mcp = MCPServer("seagoat", version=__version__)


@mcp.tool()
def search_code(
    query: str,
    limit: int = 10,
    repo_path: str = "",
    context_above: int = 3,
    context_below: int = 3,
) -> str:
    """
    Search the codebase for a given query.

    Args:
        query (str): The search query.
        limit (int): The maximum number of results to return.
        repo_path (str): The path to the repository.
        context_above (int): The number of lines of context to include above the result.
        context_below (int): The number of lines of context to include below the result.

    Returns:
        str: The search results formatted as a string.
    """
    if not query:
        return "Error: query is required."
    try:
        repo = normalize_repo_path(resolve_repo_path(repo_path or os.getcwd()))
    except (OSError, ValueError) as e:
        return f"Error normalizing repo path: {e!s}"

    running = running_instance()
    if running is None:
        return (
            f"No instance info found for repo: {repo}. Is the SeaGOAT server running?"
        )

    address = instance_url(running[0])

    try:
        result = requests.post(
            f"{address}/lines/query",
            json={
                "queryText": query,
                "limitClue": str(limit),
                "contextAbove": str(context_above),
                "contextBelow": str(context_below),
                "repoPath": repo,
            },
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        return f"Error querying server at {address} - {e!s}"

    if not result.ok:
        try:
            error_message = result.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            error_message = f"HTTP {result.status_code}"
        return f"Error querying server at {address} - {error_message}"

    data = result.json()

    results = data.get("results", [])

    output_lines = []

    if not results:
        return "No results found."

    for res in results:
        file_path = res["path"]
        output_lines.append(f"File: {file_path}\n")

        for block in res["blocks"]:
            for line in block["lines"]:
                line_num = line["line"]
                content = line["lineText"]
                output_lines.append(f"{line_num}: {content}\n")
            output_lines.append("\n")

    return "\n".join(output_lines)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
