import pytest

from seagoat.cli import display_results
from tests.fixtures.realistic_repo import SAMPLE_QUERIES


@pytest.mark.parametrize(
    "query",
    SAMPLE_QUERIES,
)
@pytest.mark.parametrize("max_results", [None, 15])
@pytest.mark.parametrize("vimgrep", ["", "vimgrep"])
def test_snapshot_results_with_real_repo(
    realistic_engine, query, snapshot, mocker, max_results, vimgrep
):
    output = {"value": ""}

    def fake_echo(message, *args, **kwargs):
        output["value"] += message + "\n"

    mocker.patch("seagoat.utils.cli_display.click.echo", side_effect=fake_echo)
    results = [result.to_json() for result in realistic_engine.query_sync(query)]
    display_results(
        results,
        max_results=max_results,
        color_enabled=False,
        vimgrep=vimgrep == "vimgrep",
    )
    assert output["value"] == snapshot
