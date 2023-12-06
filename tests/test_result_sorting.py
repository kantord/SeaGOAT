def test_sort_results_test1(create_prepared_seagoat):
    ripgrep_lines = {
        "file1.md": [(1, 10.0), (2, 4.0)],
        "file2.md": [(1, 5.0)],
    }
    chroma_lines = {
        "file2.md": [(2, 6.0)],
        "file3.md": [(1, 4.5)],
    }
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.query_sync(my_query)

    assert [result.gitfile.path for result in results] == [
        "file1.md",
        "file3.md",
        "file2.md",
    ]


def test_sort_results_test2(create_prepared_seagoat):
    ripgrep_lines = {
        "file1.md": [(1, 10.0)],
        "file2.md": [(1, 15.0)],
    }
    chroma_lines = {
        "file3.md": [(1, 5.0)],
    }
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.query_sync(my_query)

    assert [result.gitfile.path for result in results] == [
        "file3.md",
        "file1.md",
        "file2.md",
    ]


def test_missing_file_in_one_source(create_prepared_seagoat):
    ripgrep_lines = {
        "file1.md": [(1, 10.0)],
        "file2.md": [(1, 5.0)],
    }
    chroma_lines = {
        "file1.md": [(1, 6.0)],
    }
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.query_sync(my_query)

    assert [result.gitfile.path for result in results] == ["file2.md", "file1.md"]


def test_no_lines(create_prepared_seagoat):
    ripgrep_lines = {}
    chroma_lines = {}
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.query_sync(my_query)

    assert results == []


def test_file_edits_influence_order(create_prepared_seagoat, repo):
    repo.add_file_change_commit(
        file_name="file_few_edits.md",
        contents="Some content",
        author=repo.actors["John Doe"],
        commit_message="Edit file_few_edits.md",
    )

    for i in range(10):
        for j in range(3):
            repo.add_file_change_commit(
                file_name=f"file_with_some_edits_{i}.md",
                contents=f"Some content {i} {j}",
                author=repo.actors["John Doe"],
                commit_message="Edit file_many_edits.md",
            )
            repo.tick_fake_date(days=1)

    for i in range(20):
        repo.add_file_change_commit(
            file_name="file_many_edits.md",
            contents=f"Some content {i}",
            author=repo.actors["John Doe"],
            commit_message="Edit file_many_edits.md",
        )
        repo.tick_fake_date(days=1)

    ripgrep_lines = {
        "file_few_edits.md": [(1, 5.0)],
        "file_many_edits.md": [(1, 6.0)],
    }
    chroma_lines = {
        "file_few_edits.md": [(2, 5.0)],
        "file_many_edits.md": [(1, 6.0)],
        "random.py": [(1, 60.01)],
        "things.js": [(1, 160.01)],
    }
    my_query = "asdfadsfdfdffdafafdsfadsf"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    seagoat.analyze_codebase()
    results = seagoat.query_sync(my_query)

    assert [result.gitfile.path for result in results][0:2] == [
        "file_many_edits.md",
        "file_few_edits.md",
    ]
