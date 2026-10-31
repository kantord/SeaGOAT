import threading
from pathlib import Path

import pytest

from seagoat.projects import (
    NotAGitRepo,
    Projects,
    UnknownProject,
    find_repositories_in_directory,
    git_root,
)
from seagoat.utils.server import normalize_repo_path
from tests.fixtures.git import make_git_repo


def test_get_on_root_and_subdirectory_return_same_project(repo):
    root = str(repo.working_dir)
    subdirectory = str(Path(root) / "subdirectory")
    Path(subdirectory).mkdir(exist_ok=True)

    queue_factory_calls = []

    def queue_factory(repo_path, config):
        queue_factory_calls.append((repo_path, config))
        return object()

    projects = Projects(queue_factory)
    project_from_root = projects.get(root)
    project_from_subdirectory = projects.get(subdirectory)

    assert project_from_root is project_from_subdirectory
    assert len(queue_factory_calls) == 1
    assert queue_factory_calls[0][0] == normalize_repo_path(root)
    assert isinstance(queue_factory_calls[0][1], dict)
    assert "server" in queue_factory_calls[0][1]


def test_get_on_non_repository_raises_not_a_git_repo(tmp_path):
    projects = Projects(lambda repo_path, config: object())

    with pytest.raises(NotAGitRepo):
        projects.get(str(tmp_path))


def test_find_only_returns_existing_projects(repo):
    root = str(repo.working_dir)
    subdirectory = str(Path(root) / "subdirectory")
    Path(subdirectory).mkdir(exist_ok=True)

    resolve_calls = []

    def resolve(path):
        resolve_calls.append(path)
        return git_root(path)

    projects = Projects(lambda repo_path, config: object(), resolve=resolve)

    with pytest.raises(UnknownProject):
        projects.find(root)
    assert resolve_calls == []

    project = projects.get(root)
    assert resolve_calls == [root]

    assert projects.find(root) is project
    assert resolve_calls == [root]

    with pytest.raises(UnknownProject):
        projects.find(subdirectory)
    assert resolve_calls == [root]


def test_two_repositories_give_two_projects(generate_repo):
    first_repo = generate_repo()
    second_repo = generate_repo()

    projects = Projects(lambda repo_path, config: object())
    first_project = projects.get(str(first_repo.working_dir))
    second_project = projects.get(str(second_repo.working_dir))

    assert first_project is not second_project
    assert set(projects.repo_paths()) == {
        normalize_repo_path(first_repo.working_dir),
        normalize_repo_path(second_repo.working_dir),
    }


def test_concurrent_get_creates_one_project(generate_repo):
    repo = generate_repo()
    queue_factory_calls = []

    def queue_factory(repo_path, config):
        queue_factory_calls.append(repo_path)
        return object()

    projects = Projects(queue_factory)
    root = str(repo.working_dir)
    num_threads = 8
    barrier = threading.Barrier(num_threads)
    results = []

    def ask():
        barrier.wait()
        results.append(projects.get(root))

    threads = [threading.Thread(target=ask) for _ in range(num_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(queue_factory_calls) == 1
    assert all(result is results[0] for result in results)
    assert projects.find(root) is results[0]


def test_find_repositories_in_directory_returns_only_direct_repository_roots(
    tmp_path,
):
    parent = tmp_path / "projects"
    repo_a = make_git_repo(parent / "a")
    repo_b = make_git_repo(parent / "b")

    repositories = find_repositories_in_directory(str(parent))

    assert repositories == sorted(
        [normalize_repo_path(str(repo_a)), normalize_repo_path(str(repo_b))]
    )


def test_find_repositories_in_directory_skips_non_repos_and_deeper_repos(tmp_path):
    parent = tmp_path / "projects"
    repo_child = make_git_repo(parent / "repo-child")
    # A deeper repository inside a plain subdirectory is not a direct child
    deep_repo = make_git_repo(parent / "nested" / "deep")
    parent.mkdir(exist_ok=True)
    (parent / "plain").mkdir()

    repositories = find_repositories_in_directory(str(parent))

    assert repositories == [normalize_repo_path(str(repo_child))]
    assert normalize_repo_path(str(deep_repo)) not in repositories
    assert normalize_repo_path(str(parent / "nested")) not in repositories


def test_find_repositories_in_directory_returns_empty_without_repositories(tmp_path):
    parent = tmp_path / "projects"
    parent.mkdir()
    (parent / "plain").mkdir()
    (parent / "file.txt").write_text("hello", encoding="utf-8")

    assert find_repositories_in_directory(str(parent)) == []


def test_find_repositories_in_directory_returns_empty_for_missing_directory(tmp_path):
    assert find_repositories_in_directory(str(tmp_path / "does-not-exist")) == []
