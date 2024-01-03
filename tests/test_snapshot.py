import pytest
from seagoat.cli import display_results


@pytest.mark.parametrize(
    "query",
    [
        ("I want to use a pink color on my led while I'm working"),
        ("where do we decide what type of status bar app to use"),
        ("installation instructions for arch linux"),
    ],
)
@pytest.mark.parametrize("max_results", [None, 15])
@pytest.mark.parametrize("vimgrep", ["", "vimgrep"])
def test_snapshot_results_with_real_repo(
    realistic_server, query, snapshot, mocker, max_results, vimgrep
):
    output = {"value": ""}

    def fake_echo(message, *args, **kwargs):
        output["value"] += message + "\n"

    mocker.patch("seagoat.utils.cli_display.click.echo", side_effect=fake_echo)
    results = [result.to_json() for result in realistic_server.query_sync(query)]
    display_results(
        results,
        max_results=max_results,
        color_enabled=False,
        vimgrep=vimgrep == "vimgrep",
    )
    assert output["value"] == snapshot
