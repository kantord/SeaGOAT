"""
Tests for the MCP server.
"""

from unittest.mock import MagicMock
from typing import Dict, Any

import pytest
from pytest_mock import MockerFixture

from seagoat.mcp_server import search_code
from seagoat.utils.server import ServerDoesNotExist


@pytest.fixture
def mock_mcp_deps(mocker: MockerFixture) -> Dict[str, Any]:
    """Mock dependencies for MCP server tests."""
    return {
        "normalize": mocker.patch("seagoat.mcp_server.normalize_repo_path"),
        "get_server_info": mocker.patch("seagoat.mcp_server.get_server_info"),
        "post": mocker.patch("seagoat.mcp_server.requests.post"),
    }


def test_search_code_success(mock_mcp_deps) -> None:
    """Test successful code search."""
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["get_server_info"].return_value = {
        "address": "http://localhost:1234",
        "port": 1234,
    }

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "path": "test_file.py",
                "blocks": [
                    {
                        "lines": [
                            {"line": 10, "lineText": "def test_func():"},
                            {"line": 11, "lineText": "    pass"},
                        ]
                    }
                ],
            }
        ]
    }
    mock_mcp_deps["post"].return_value = mock_response

    result = search_code("test query", repo_path=".")

    assert "File: test_file.py" in result
    assert "def test_func():" in result


def test_search_code_server_not_running(mock_mcp_deps) -> None:
    """Test behavior when server is not running."""
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["get_server_info"].side_effect = ServerDoesNotExist(
        "Server not found"
    )

    result = search_code("test query", repo_path=".")

    assert (
        "No server info found" in result
        or "Server not found" in result
        or "Is the seagoat server running?" in result
    )


def test_search_code_no_results(mock_mcp_deps) -> None:
    """Test when no results are found."""
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["get_server_info"].return_value = {"address": "http://localhost:1234"}

    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_mcp_deps["post"].return_value = mock_response

    result = search_code("test query", repo_path=".")

    assert "No results found" in result


def test_search_code_missing_query() -> None:
    """Test when query matches nothing."""
    result = search_code("", repo_path=".")
    assert "Error: query is required" in result
