import datetime
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import pytest
from freezegun import freeze_time
from hypothesis import given, settings
from hypothesis import strategies as st
from pytest_mock import MockerFixture

from seagoat.engine import Engine
from seagoat.repository import Repository
from tests.fixtures.mock_repo import MockRepo


def test_lists_files_of_the_repository(repo):
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    assert {file.path for file, _ in seagoat.repository.top_files()} == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }
    assert set(seagoat.repository.get_file("file1.md").commit_messages) == {
        "Initial commit for Markdown file",
        "Update to Markdown file",
    }


def test_lists_files_committed_after_engine_creation(repo):
    seagoat = Engine(repo.working_dir)
    repo.add_file_change_commit(
        file_name="new_file.cpp",
        contents="#include <iostream>",
        commit_message="Initial commit for C++ file",
    )
    seagoat.analyze_codebase()

    assert {file.path for file, _ in seagoat.repository.top_files()} == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
        "new_file.cpp",
    }
    assert set(seagoat.repository.get_file("new_file.cpp").commit_messages) == {
        "Initial commit for C++ file"
    }


def test_file_change_many_times_is_first_result(repo):
    seagoat = Engine(repo.working_dir)
    for i in range(10):
        repo.add_file_change_commit(
            file_name="new_file.txt",
            contents=f"{i}",
            commit_message="add my file",
        )
        repo.tick_fake_date(minutes=1)
    seagoat.analyze_codebase(minimum_chunks_to_analyze=2)

    assert seagoat.repository.top_files()[0][0].path == "new_file.txt"


def test_newer_change_can_beat_frequent_change_in_past(repo):
    seagoat = Engine(repo.working_dir)
    for i in range(10):
        repo.add_file_change_commit(
            file_name="old_file.txt",
            contents=f"{i}",
            commit_message="add my file",
        )
    repo.tick_fake_date(days=300)
    repo.add_file_change_commit(
        file_name="new_file.txt",
        contents="hello",
        commit_message="add another file",
    )
    seagoat.analyze_codebase()

    assert seagoat.repository.top_files()[0][0].path == "new_file.txt"


def test_commit_messages_with_three_or_more_colons(repo):
    seagoat = Engine(repo.working_dir)
    commit_messages = set()
    for i in range(5):
        message = "add my file" + ":" * i + "!"
        commit_messages.add(message)
        repo.add_file_change_commit(
            file_name="file.txt",
            contents=f"{i}",
            commit_message=message,
        )
    seagoat.analyze_codebase()

    assert (
        set(seagoat.repository.get_file("file.txt").commit_messages) == commit_messages
    )


def test_ignores_certain_branches(repo):
    seagoat = Engine(repo.working_dir)
    main = repo.active_branch
    new_branch = repo.create_head("gh-pages")
    new_branch.checkout()
    repo.add_file_change_commit(
        file_name="file_on_other_branch.cpp",
        contents="",
        commit_message="add my file",
    )
    main.checkout()
    seagoat.analyze_codebase()

    assert not any(
        file.path == "file_on_other_branch.cpp"
        for file, _ in seagoat.repository.top_files()
    )


def test_analysis_results_are_persisted_between_runs(repo):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    seagoat2.analyze_codebase()

    assert {file.path for file, _ in seagoat2.repository.top_files()} == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


@pytest.mark.parametrize(
    "damage_cache",
    [
        pytest.param(
            lambda cache_folder: (cache_folder / "cache").write_bytes(
                (cache_folder / "cache").read_bytes()[:-1]
            ),
            id="truncated",
        ),
        pytest.param(
            lambda cache_folder: (cache_folder / "cache").write_bytes(b""),
            id="empty",
        ),
    ],
)
def test_damaged_cache_does_not_crash_app(repo, damage_cache):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    cache_folder = seagoat1.cache.get_cache_folder()
    damage_cache(cache_folder)
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    seagoat2.analyze_codebase()

    assert {file.path for file, _ in seagoat2.repository.top_files()} == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_analyze_codebase_caps_minimum_chunks_to_analyze(repo):
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase(minimum_chunks_to_analyze=10_000)

    assert {file.path for file, _ in seagoat.repository.top_files()} == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_only_returns_supported_file_types(repo):
    seagoat = Engine(repo.working_dir)
    for i in range(10):
        repo.add_file_change_commit(
            file_name=f"new_file.txt.extension{i}",
            contents=f"{i}",
            commit_message="add my file",
        )
    seagoat.analyze_codebase()

    assert {file.path for file, _ in seagoat.repository.top_files()} == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }
    assert set(seagoat.repository.get_file("file1.md").commit_messages) == {
        "Initial commit for Markdown file",
        "Update to Markdown file",
    }


def test_file_score_is_recalculated_when_needed(generate_fresh_repo):
    with freeze_time("2012-01-14"):
        repo1 = generate_fresh_repo()
        seagoat1 = Engine(repo1.working_dir)
        repo1.add_file_change_commit(
            file_name="old_file.txt",
            contents="",
            commit_message="add my file",
        )
        repo1.tick_fake_date(days=300)
        repo1.add_file_change_commit(
            file_name="new_file.txt",
            contents="hello",
            commit_message="add another file",
        )
        seagoat1.analyze_codebase()

        repo2 = generate_fresh_repo()
        seagoat2 = Engine(repo1.working_dir)
        repo2.add_file_change_commit(
            file_name="old_file.txt",
            contents="",
            commit_message="add my file",
        )
        seagoat2.analyze_codebase()

    assert (
        seagoat1.repository.get_file("file1.md").score
        == seagoat2.repository.get_file("file1.md").score
    )

    with freeze_time("2018-01-15"):
        repo2.tick_fake_date(days=300)
        repo2.add_file_change_commit(
            file_name="new_file.txt",
            contents="hello",
            commit_message="add another file",
        )
        seagoat2.analyze_codebase()

    assert (
        seagoat1.repository.get_file("file1.md").score
        != seagoat2.repository.get_file("file1.md").score
    )


def test_does_not_crash_because_of_non_existent_files(repo):
    seagoat = Engine(repo.working_dir)
    (Path(repo.working_dir) / "file1.md").unlink()
    seagoat.analyze_codebase()

    assert {file.path for file, _ in seagoat.repository.top_files()} == {
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_ignored_files_is_really_ignored(repo: MockRepo):
    file_name = "node_modules/acorn/README.md"
    repo.add_file_change_commit(
        file_name=file_name,
        contents="Hello",
        commit_message="Incidentally commited node_modules.",
    )
    repo.add_file_change_commit(
        file_name=".gitignore",
        contents="node_modules",
        commit_message="Added node_modules to gitignore.",
    )
    repo.add_file_delete_commit(
        file_name=file_name,
        commit_message="Removed node_modules.",
    )
    # File is added in the filesystem, but should be ignored by git.
    file_path = Path(repo.working_dir) / file_name
    file_path.write_text("Hello.")

    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    top_files = {file.path for file, _ in seagoat.repository.top_files()}

    assert file_name not in top_files


def test_does_not_crash_because_of_untracked_files_that_used_to_be_tracked(
    repo: MockRepo,
):
    file_name = "notes.py"
    repo.add_file_change_commit(
        file_name=file_name,
        contents="notes = 1",
        commit_message="Added notes.",
    )
    repo.add_file_delete_commit(
        file_name=file_name,
        commit_message="Removed notes.",
    )
    # The file is re-created in the filesystem, but it is not tracked by git
    # and it is not ignored either, so it is part of the history of the
    # repository and of the working tree, but not of HEAD.
    (Path(repo.working_dir) / file_name).write_text("notes = 2")

    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    assert {file.path for file, _ in seagoat.repository.top_files()} == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_file_that_is_not_part_of_head_has_no_object_id(repo: MockRepo):
    (Path(repo.working_dir) / "untracked.py").write_text("untracked = 1")
    repository = Repository(repo.working_dir)

    assert repository.get_file_object_id("file2.py") is not None
    assert repository.get_file_object_id("untracked.py") is None
    assert not repository.is_up_to_date_git_object("untracked.py", "0" * 40)


def test_does_not_crash_in_a_repository_without_commits(tmp_path: Path):
    MockRepo.init(str(tmp_path)).close()
    (tmp_path / "file1.py").write_text("file = 1")
    repository = Repository(str(tmp_path))

    repository.analyze_files()

    assert repository.top_files() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks_to_analyze", [1, 2, 4])
async def test_allows_limiting_how_many_files_are_automatically_analized(
    repo, chunks_to_analyze
):
    seagoat = Engine(repo.working_dir)
    repo.add_file_change_commit(
        file_name="new_file.cpp",
        contents="#include <iostream>",
        commit_message="Initial commit for C++ file",
    )
    seagoat.analyze_codebase(minimum_chunks_to_analyze=chunks_to_analyze)

    assert len(seagoat.cache.data["chunks_already_analyzed"]) == chunks_to_analyze


@pytest.mark.parametrize(
    "config,expected_extra_args",
    [
        pytest.param({}, ["--max-count=5000"], id="default"),
        pytest.param(
            {"readMaxCommits": 100}, ["--max-count=100"], id="specific-number"
        ),
        pytest.param({"readMaxCommits": None}, [], id="unlimited"),
    ],
)
def test_max_count_is_added_for_read_max_commits_setting(
    repo: MockRepo,
    mocker: MockerFixture,
    config: dict[str, Any],
    expected_extra_args: list[str],
):
    repository = Engine(repo.working_dir).repository
    repository.config["server"].update(config)
    mock = mocker.spy(repository, "_git_log_extra_options")

    repository.analyze_files()

    assert mock.spy_return == expected_extra_args


def test_get_blobs_data_matches_get_blob_data(repo: MockRepo):
    repo.add_file_change_commit(
        file_name="a.py",
        contents="first file\nwith two lines\n",
        commit_message="Add a.py",
    )
    repo.add_file_change_commit(
        file_name="b.md",
        contents="",
        commit_message="Add empty b.md",
    )
    repository = Repository(repo.working_dir)
    object_ids = []
    for path in ["a.py", "b.md", "file1.md"]:
        object_id = repository.get_file_object_id(path)
        assert object_id is not None
        object_ids.append(object_id)
    missing_object_id = "0" * 40

    blobs = repository.get_blobs_data([*object_ids, missing_object_id])

    assert blobs == {
        object_id: repository.get_blob_data(object_id) for object_id in object_ids
    }


def test_parse_commit_info_handles_commits_from_timezones_ahead():
    from seagoat.repository import parse_commit_info

    with freeze_time("2024-01-01 12:00:00", tz_offset=0):
        commit_hash, days_passed, author, subject = parse_commit_info(
            "abc:::2024-01-02 01:00:00 +1400:::A <a@b>:::subject"
        )

    assert days_passed == 0
    assert (commit_hash, author, subject) == ("abc", "A <a@b>", "subject")


def test_parse_commit_info_clamps_future_commits_to_zero():
    from seagoat.repository import parse_commit_info

    with freeze_time("2024-01-01 12:00:00", tz_offset=0):
        _, days_passed, _, _ = parse_commit_info(
            "abc:::2030-01-01 00:00:00 +0000:::A <a@b>:::subject"
        )

    assert days_passed == 0


def test_compute_frecency_does_not_crash_on_future_commit():
    from seagoat.repository import parse_commit_info

    with freeze_time("2024-01-01 12:00:00", tz_offset=0):
        commit_info = parse_commit_info(
            "abc:::2025-01-01 00:00:00 +0000:::A <a@b>:::subject"
        )

    repository = Repository.__new__(Repository)
    repository.file_changes = defaultdict(list)
    repository.file_changes["file1.py"] = [commit_info]
    repository.frecency_scores = {}

    repository._compute_frecency()

    assert repository.frecency_scores["file1.py"] > 0


@settings(deadline=None, max_examples=50)
@given(
    commit_naive=st.datetimes(
        min_value=datetime.datetime(2000, 1, 1),
        max_value=datetime.datetime(2100, 1, 1),
    ),
    offset_minutes=st.integers(-840, 840),
    delta_days=st.integers(0, 1000),
)
def test_parse_commit_info_frecency_property(commit_naive, offset_minutes, delta_days):
    from seagoat.repository import parse_commit_info

    commit_tz = datetime.timezone(datetime.timedelta(minutes=offset_minutes))
    commit_aware = commit_naive.replace(tzinfo=commit_tz)
    commit_utc_naive = commit_aware.astimezone(datetime.UTC).replace(tzinfo=None)
    now_aware = (commit_utc_naive + datetime.timedelta(days=delta_days)).replace(
        tzinfo=datetime.UTC
    )

    commit_str = commit_naive.strftime("%Y-%m-%d %H:%M:%S ") + commit_aware.strftime(
        "%z"
    )

    with freeze_time(now_aware):
        _, days_passed, _, _ = parse_commit_info(
            f"abc:::{commit_str}:::A <a@b>:::subject"
        )

    expected = (
        now_aware.astimezone(datetime.UTC).date()
        - commit_aware.astimezone(datetime.UTC).date()
    ).days

    assert days_passed == expected
    assert days_passed >= 0


def test_top_files_are_sorted_by_score_descending(repo):
    seagoat = Engine(repo.working_dir)
    repo.tick_fake_date(days=-100)
    repo.add_file_change_commit(
        file_name="least_frecent.txt",
        contents="least frecent",
        commit_message="add least frecent file",
    )
    repo.tick_fake_date(days=300)
    for i in range(10):
        repo.add_file_change_commit(
            file_name="most_frecent.txt",
            contents=f"{i}",
            commit_message="add most frecent file",
        )
    seagoat.analyze_codebase()

    top_files = seagoat.repository.top_files()
    scores = [score for _, score in top_files]

    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)), (
        "scores should be non-increasing in top_files order"
    )
    assert top_files[0][0].path == "most_frecent.txt"
    assert top_files[-1][0].path == "least_frecent.txt"


def test_analyze_files_preserves_whitespace_and_quoted_filenames(repo: MockRepo):
    repository = Repository(repo.working_dir)
    weird_names = [
        "file with spaces.py",
        'file"with"quotes.py',
        "file\twith\ttab.py",
        "file\nwith\nnewline.py",
        "file\rwith\rcarriage-return.py",
    ]
    for name in weird_names:
        repo.add_file_change_commit(
            file_name=name,
            contents=f"content for {name}\n",
            commit_message=f"Commit for {name!r}",
        )

    repository.analyze_files()

    # The newline-named file is the only file in its commit, so it goes
    # through the header-attached path of the git log parser.
    assert set(weird_names) <= set(repository.file_changes)
    for name in weird_names:
        assert repository.file_changes[name], name


def test_analyze_files_supports_valid_committed_empty_repository(tmp_path: Path):
    repo = cast(MockRepo, MockRepo.init(str(tmp_path)))
    repo.index.commit(
        "empty commit with no files",
        author=repo.actors["John Doe"],
        committer=repo.actors["John Doe"],
        skip_hooks=True,
    )
    repo.close()
    repository = Repository(str(tmp_path))

    repository.analyze_files()

    assert repository.file_changes == {}
    assert repository.frecency_scores == {}
    assert repository.top_files() == []


def _patch_command(mocker, matcher, returncode, stdout="", stderr="failure"):
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if matcher(cmd):
            output = stdout if kwargs.get("text") else stdout.encode("utf-8")
            errors = stderr if kwargs.get("text") else stderr.encode("utf-8")
            return subprocess.CompletedProcess(cmd, returncode, output, errors)
        return real_run(cmd, *args, **kwargs)

    return mocker.patch("seagoat.repository.subprocess.run", side_effect=fake_run)


def test_analyze_files_keeps_previous_state_when_ripgrep_fails(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    previous_frecency = dict(repository.frecency_scores)
    assert previous_changes

    _patch_command(mocker, lambda cmd: bool(cmd) and cmd[0] == "rg", 2)
    with pytest.raises(RuntimeError, match="ripgrep"):
        repository.analyze_files()

    assert dict(repository.file_changes) == previous_changes
    assert repository.frecency_scores == previous_frecency


def test_analyze_files_keeps_previous_state_when_ls_tree_fails(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    previous_frecency = dict(repository.frecency_scores)
    assert previous_changes

    _patch_command(mocker, lambda cmd: bool(cmd) and "ls-tree" in cmd, 128)
    with pytest.raises(RuntimeError, match="ls-tree"):
        repository.analyze_files()

    assert dict(repository.file_changes) == previous_changes
    assert repository.frecency_scores == previous_frecency


def test_analyze_files_keeps_previous_state_when_git_log_fails(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    previous_frecency = dict(repository.frecency_scores)
    assert previous_changes

    _patch_command(
        mocker,
        lambda cmd: bool(cmd) and cmd[0] == "git" and "log" in cmd,
        128,
    )
    with pytest.raises(RuntimeError, match="git log"):
        repository.analyze_files()

    assert dict(repository.file_changes) == previous_changes
    assert repository.frecency_scores == previous_frecency


def test_analyze_files_keeps_previous_state_on_partial_git_log_stream(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    previous_frecency = dict(repository.frecency_scores)
    assert previous_changes

    # Successful exit code but the NUL-delimited stream is cut off in the
    # middle of the next commit's header: the parser must notice the
    # truncation instead of silently publishing a partial result.
    partial_stream = (
        "\x00###abc:::2024-01-01 00:00:00 +0000:::A <a@b>:::subject\nfile1.py\x00\x00#"
    )
    _patch_command(
        mocker,
        lambda cmd: bool(cmd) and cmd[0] == "git" and "log" in cmd,
        0,
        stdout=partial_stream,
    )
    with pytest.raises(RuntimeError, match="malformed git log output"):
        repository.analyze_files()

    assert dict(repository.file_changes) == previous_changes
    assert repository.frecency_scores == previous_frecency


def test_analyze_files_retries_and_publishes_when_head_changes(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    assert previous_changes

    heads = iter(["1" * 40, "2" * 40, "2" * 40, "2" * 40])
    scanned_heads = []
    mocker.patch.object(repository, "_get_scan_head", side_effect=lambda: next(heads))

    def fake_scan(head):
        scanned_heads.append(head)
        return {f"scanned_{head[:1]}.py": [("###abc", 0, "A <a@b>", "s")]}, {
            f"scanned_{head[:1]}.py": 1.0
        }

    mocker.patch.object(repository, "_scan_at_head", side_effect=fake_scan)

    repository.analyze_files()

    # First scan observed a moved HEAD and was retried at the new revision.
    assert scanned_heads == ["1" * 40, "2" * 40]
    assert dict(repository.file_changes) == {
        "scanned_2.py": [("###abc", 0, "A <a@b>", "s")]
    }
    assert repository.frecency_scores == {"scanned_2.py": 1.0}


def test_analyze_files_raises_and_keeps_state_when_head_keeps_changing(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    previous_frecency = dict(repository.frecency_scores)
    assert previous_changes

    heads = ["1" * 40, "2" * 40] * 4
    mocker.patch.object(repository, "_get_scan_head", side_effect=lambda: heads.pop(0))
    mocker.patch.object(
        repository,
        "_scan_at_head",
        side_effect=lambda head: ({"moved.py": []}, {"moved.py": 1.0}),
    )

    with pytest.raises(RuntimeError, match="HEAD kept changing"):
        repository.analyze_files()

    assert dict(repository.file_changes) == previous_changes
    assert repository.frecency_scores == previous_frecency


def test_analyze_files_raises_outside_a_git_repository(tmp_path: Path):
    repository = Repository(str(tmp_path))

    with pytest.raises(RuntimeError, match="not a valid git working tree"):
        repository.analyze_files()


def test_failed_head_lookup_preserves_previous_scan_on_existing_branch(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    previous_frecency = dict(repository.frecency_scores)
    _patch_command(
        mocker,
        lambda cmd: "rev-parse" in cmd and "--verify" in cmd,
        128,
    )

    with pytest.raises(RuntimeError, match="could not resolve HEAD"):
        repository.analyze_files()

    assert dict(repository.file_changes) == previous_changes
    assert repository.frecency_scores == previous_frecency


def test_git_log_header_prefix_in_filename_is_not_a_commit(repo):
    names = ["!-first.py", "###last.py"]
    for name in names:
        Path(repo.working_dir, name).write_text("value = 1\n")
    repo.index.add(names)
    repo.index.commit(
        "Add two paths in the same commit",
        author=repo.actors["John Doe"],
        committer=repo.actors["John Doe"],
        skip_hooks=True,
    )
    repository = Repository(repo.working_dir)

    repository.analyze_files()

    assert set(names) <= set(repository.file_changes)


def test_first_commit_during_unborn_scan_does_not_publish_empty_state(repo, mocker):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    previous_changes = dict(repository.file_changes)
    head = "1" * 40
    mocker.patch.object(
        repository, "_get_scan_head", side_effect=[None, head, head, head]
    )

    def completed_scan(revision):
        assert revision == head
        assert dict(repository.file_changes) == previous_changes
        return {"new.py": []}, {"new.py": 1.0}

    mocker.patch.object(repository, "_scan_at_head", side_effect=completed_scan)

    repository.analyze_files()

    assert dict(repository.file_changes) == {"new.py": []}
    assert repository.frecency_scores == {"new.py": 1.0}
