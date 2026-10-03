from pathlib import Path

from seagoat.repository import Repository
from seagoat.sources.ripgrep import initialize


def test_empty_ripgrep_cache_returns_no_results(repo):
    for filename in ["file1.md", "file2.py", "file3.py", "file4.js", "file4.md"]:
        (Path(repo.working_dir) / filename).unlink(missing_ok=True)
    (Path(repo.working_dir) / "rock.mp3").write_text("12345", encoding="utf-8")

    my_repo = Repository(repo.working_dir)
    my_repo.analyze_files()
    source = initialize(my_repo)
    source["cache_repo"]()

    assert not list(source["fetch"]("anything", limit=10))
