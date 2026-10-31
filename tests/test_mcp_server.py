"""
Tests for the MCP server.
"""

import os
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from seagoat.mcp_server import search_code
from seagoat.utils.server import Instance, normalize_repo_path


@pytest.fixture
def mock_mcp_deps(mocker: MockerFixture) -> dict[str, Any]:
    """Mock dependencies for MCP server tests."""
    return {
        "normalize": mocker.patch("seagoat.mcp_server.normalize_repo_path"),
        "read_instance": MagicMock(),  # only holds the Instance for running_instance
        "running_instance": mocker.patch("seagoat.mcp_server.running_instance"),
        "instance_url": mocker.patch("seagoat.mcp_server.instance_url"),
        "post": mocker.patch("seagoat.mcp_server.requests.post"),
        "resolve": mocker.patch("seagoat.mcp_server.resolve_repo_path"),
    }


def test_search_code_success(mock_mcp_deps) -> None:
    """Test successful code search."""
    mock_mcp_deps["resolve"].return_value = "."
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["read_instance"].return_value = Instance(
        host="localhost", port=1234, pid=1
    )
    mock_mcp_deps["running_instance"].return_value = (
        mock_mcp_deps["read_instance"].return_value,
        {"pid": 1},
    )
    mock_mcp_deps["instance_url"].return_value = "http://localhost:1234"

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

    mock_mcp_deps["post"].assert_called_once()
    request_body = mock_mcp_deps["post"].call_args.kwargs["json"]
    assert request_body["repoPath"] == "/abs/path/to/repo"


def test_search_code_server_not_running(mock_mcp_deps) -> None:
    """Test behavior when server is not running."""
    mock_mcp_deps["resolve"].return_value = "."
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["read_instance"].return_value = None
    mock_mcp_deps["running_instance"].return_value = None

    result = search_code("test query", repo_path=".")

    assert "No instance info found" in result
    assert "Is the SeaGOAT server running?" in result
    mock_mcp_deps["post"].assert_not_called()


def test_search_code_no_results(mock_mcp_deps) -> None:
    """Test when no results are found."""
    mock_mcp_deps["resolve"].return_value = "."
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["read_instance"].return_value = Instance(
        host="localhost", port=1234, pid=1
    )
    mock_mcp_deps["running_instance"].return_value = (
        mock_mcp_deps["read_instance"].return_value,
        {"pid": 1},
    )
    mock_mcp_deps["instance_url"].return_value = "http://localhost:1234"

    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_mcp_deps["post"].return_value = mock_response

    result = search_code("test query", repo_path=".")

    assert "No results found" in result

    mock_mcp_deps["post"].assert_called_once()
    request_body = mock_mcp_deps["post"].call_args.kwargs["json"]
    assert request_body["repoPath"] == "/abs/path/to/repo"


def test_search_code_missing_query() -> None:
    """Test when query matches nothing."""
    result = search_code("", repo_path=".")
    assert "Error: query is required" in result


def test_search_code_sends_repository_root_for_subdirectory(repo, mocker) -> None:
    """Test that a subdirectory's repository root is sent as repoPath."""
    subdirectory = os.path.join(repo.working_dir, "subdirectory")
    os.makedirs(subdirectory, exist_ok=True)

    instance = Instance(host="localhost", port=1234, pid=1)
    mocker.patch(
        "seagoat.mcp_server.running_instance",
        return_value=(instance, {"pid": instance.pid}),
    )
    mocker.patch(
        "seagoat.mcp_server.instance_url", return_value="http://localhost:1234"
    )
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    post = mocker.patch("seagoat.mcp_server.requests.post", return_value=mock_response)

    result = search_code("test query", repo_path=subdirectory)

    assert "No results found" in result
    request_body = post.call_args.kwargs["json"]
    assert request_body["repoPath"] == normalize_repo_path(repo.working_dir)


def test_search_code_reports_server_error_message_for_http_error(mock_mcp_deps) -> None:
    """Test that a 4xx/5xx answer shows the server's error message, not just the status."""
    mock_mcp_deps["resolve"].return_value = "."
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["read_instance"].return_value = Instance(
        host="localhost", port=1234, pid=1
    )
    mock_mcp_deps["running_instance"].return_value = (
        mock_mcp_deps["read_instance"].return_value,
        {"pid": 1},
    )
    mock_mcp_deps["instance_url"].return_value = "http://localhost:1234"

    server_error_message = (
        "The SeaGOAT server does not serve the repository at '/abs/path/to/repo'. "
        "Run `seagoat-server start /abs/path/to/repo` to add it to the server."
    )
    mock_response = MagicMock()
    mock_response.ok = False
    mock_response.status_code = 404
    mock_response.json.return_value = {
        "code": 404,
        "error": {"type": "UnknownProject", "message": server_error_message},
    }
    mock_mcp_deps["post"].return_value = mock_response

    result = search_code("test query", repo_path=".")

    assert server_error_message in result
    assert "404 Client Error" not in result


def test_search_code_falls_back_to_status_when_error_body_has_no_message(
    mock_mcp_deps,
) -> None:
    """Test that a non-JSON error answer still reports the HTTP status."""
    mock_mcp_deps["resolve"].return_value = "."
    mock_mcp_deps["normalize"].return_value = "/abs/path/to/repo"
    mock_mcp_deps["read_instance"].return_value = Instance(
        host="localhost", port=1234, pid=1
    )
    mock_mcp_deps["running_instance"].return_value = (
        mock_mcp_deps["read_instance"].return_value,
        {"pid": 1},
    )
    mock_mcp_deps["instance_url"].return_value = "http://localhost:1234"

    mock_response = MagicMock()
    mock_response.ok = False
    mock_response.status_code = 503
    mock_response.json.side_effect = ValueError("No JSON object could be decoded")
    mock_mcp_deps["post"].return_value = mock_response

    result = search_code("test query", repo_path=".")

    assert "HTTP 503" in result
