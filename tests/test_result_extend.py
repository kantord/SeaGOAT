from hypothesis import given, settings
from hypothesis import strategies as st

from seagoat.engine import Engine
from seagoat.gitfile import GitFile
from seagoat.result import Result, ResultLineType
from tests.fixtures.sources import mock_sources_context


class _FakeRepository:
    def get_blob_data(self, object_id):
        return "\n".join(f"line {i}" for i in range(1, 51))


def make_result(line_distances):
    gitfile = GitFile(
        _FakeRepository(),
        "test.txt",
        "/test.txt",
        "abc123",
        0.5,
        [],
    )
    result = Result("test query", gitfile)
    for line, distance in line_distances.items():
        result.add_line(line, distance)
    return result


def _line_distances(result):
    return {
        line: result_line.vector_distance for line, result_line in result.lines.items()
    }


def test_extend_keeps_better_line_and_unions_types():
    a = make_result({5: 0.3})
    b = make_result({5: 1.2, 7: 1.2})
    b.lines[5].add_type(ResultLineType.CONTEXT)

    a.extend(b)

    # the better chroma line must not be replaced by the ripgrep line
    assert a.lines[5].vector_distance == 0.3
    # lines unique to the other result must still be added
    assert a.lines[7].vector_distance == 1.2
    # types from both results must be preserved
    assert ResultLineType.RESULT in a.lines[5].types
    assert ResultLineType.CONTEXT in a.lines[5].types


@settings(deadline=None, max_examples=50)
@given(
    st.dictionaries(st.integers(1, 50), st.floats(0, 2, allow_nan=False)),
    st.dictionaries(st.integers(1, 50), st.floats(0, 2, allow_nan=False)),
)
def test_extend_merges_lines_like_add_line(a_data, b_data):
    a = make_result(a_data)
    b = make_result(b_data)

    a.extend(b)

    # the set of lines is the union
    assert set(a.lines) == set(a_data) | set(b_data)
    # every line keeps the minimum distance over the inputs that have it
    for line in set(a_data) | set(b_data):
        distances = [
            distance
            for distance in (a_data.get(line), b_data.get(line))
            if distance is not None
        ]
        assert a.lines[line].vector_distance == min(distances)


@settings(deadline=None, max_examples=50)
@given(
    st.dictionaries(st.integers(1, 50), st.floats(0, 2, allow_nan=False)),
    st.dictionaries(st.integers(1, 50), st.floats(0, 2, allow_nan=False)),
)
def test_extend_is_commutative_for_distances(a_data, b_data):
    a_forward = make_result(a_data)
    b_forward = make_result(b_data)
    a_forward.extend(b_forward)

    a_reverse = make_result(a_data)
    b_reverse = make_result(b_data)
    b_reverse.extend(a_reverse)

    assert _line_distances(a_forward) == _line_distances(b_reverse)
    assert set(a_forward.lines) == set(b_reverse.lines)


def test_context_line_merged_with_a_match_keeps_the_match_distance(repo):
    # chroma: a.py line 10 (0.3) with line 11 as context below; ripgrep: a.py
    # line 11 (0.4); b.py has the best match (0.05). Merging line 11 must keep
    # ripgrep's 0.4, not the context placeholder 0.0, so a.py cannot jump
    # ahead of b.py just because context was requested.
    sources = (
        repo,
        {"a.py": [(11, 0.4)]},
        {"a.py": [(10, 0.3)], "b.py": [(5, 0.05)]},
    )
    with mock_sources_context(*sources):
        engine = Engine(repo.working_dir)
        engine.repository.analyze_files()
        with_context = engine.query_sync("zzz", context_above=0, context_below=1)
    with mock_sources_context(*sources):
        engine = Engine(repo.working_dir)
        engine.repository.analyze_files()
        without_context = engine.query_sync("zzz", context_above=0, context_below=0)

    a_result = next(r for r in with_context if r.gitfile.path == "a.py")
    assert ResultLineType.RESULT in a_result.lines[11].types
    assert a_result.lines[11].vector_distance == 0.4
    assert [r.gitfile.path for r in with_context] == [
        r.gitfile.path for r in without_context
    ]


def test_add_line_ignores_a_context_placeholder_distance(repo):
    with mock_sources_context(repo, {}, {"a.py": [(10, 0.3)]}):
        engine = Engine(repo.working_dir)
        engine.repository.analyze_files()
        result = engine.query_sync("zzz", context_above=0, context_below=1)[0]

    result.add_line(11, 0.5)

    assert result.lines[11].vector_distance == 0.5
    assert result.lines[11].types == {ResultLineType.RESULT, ResultLineType.CONTEXT}
