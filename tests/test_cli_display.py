"""Behavioural tests for seagoat.utils.cli_display.

These cover how search results are printed to the terminal:
plain text, colored highlighted source, vimgrep format, and bat.
"""

from hypothesis import given
from hypothesis import strategies as st

from seagoat.utils.cli_display import (
    display_results,
    get_highlighted_lines,
    iterate_result_blocks,
    print_result_line,
)


def _block(lines, start=1, score=0.0):
    """A result block in the shape the server sends to the CLI."""
    return {
        "score": score,
        "lineTypeCount": {"result": len(lines)},
        "lines": [
            {
                "line": line_number,
                "lineText": line_text,
                "resultTypes": ["result"],
            }
            for line_number, line_text in enumerate(lines, start=start)
        ],
    }


def _result(path, full_path, blocks):
    return {"path": path, "fullPath": str(full_path), "blocks": blocks}


def test_get_highlighted_lines_returns_markdown_as_plain_text(tmp_path):
    markdown_file = tmp_path / "README.md"
    markdown_file.write_text("Title\n\nbody text\n", encoding="utf-8")

    assert get_highlighted_lines(str(markdown_file)) == ["Title", "", "body text"]


def test_get_highlighted_lines_highlights_jsx(tmp_path):
    jsx_file = tmp_path / "Component.jsx"
    jsx_file.write_text(
        'import React from "react";\n'
        'export const App = () => <div className="app">Hi</div>;\n',
        encoding="utf-8",
    )

    highlighted_lines = get_highlighted_lines(str(jsx_file))

    assert "import" in highlighted_lines[0]
    assert "\x1b[" in highlighted_lines[0]


def test_get_highlighted_lines_highlights_tsx(tmp_path):
    tsx_file = tmp_path / "Component.tsx"
    tsx_file.write_text(
        'import React from "react";\nconst count: number = 1;\n',
        encoding="utf-8",
    )

    highlighted_lines = get_highlighted_lines(str(tsx_file))

    assert "import" in highlighted_lines[0]
    assert "number" in highlighted_lines[1]
    assert "\x1b[" in highlighted_lines[0]


def test_get_highlighted_lines_picks_lexer_from_file_name(tmp_path):
    python_file = tmp_path / "module.py"
    python_file.write_text("def foo():\n    return 42\n", encoding="utf-8")

    highlighted_lines = get_highlighted_lines(str(python_file))

    assert "def" in highlighted_lines[0]
    assert "\x1b[" in highlighted_lines[0]


def test_get_highlighted_lines_never_re_reads_the_file(tmp_path):
    markdown_file = tmp_path / "README.md"
    markdown_file.write_text("version one\n", encoding="utf-8")

    assert get_highlighted_lines(str(markdown_file)) == ["version one"]

    markdown_file.write_text("version two\n", encoding="utf-8")

    # Highlighting is cached for the lifetime of the process, so editing the
    # file on disk does not change what is printed for already-seen files.
    assert get_highlighted_lines(str(markdown_file)) == ["version one"]


def test_print_result_line_with_color_shows_highlighted_source_line(tmp_path, capsys):
    source_file = tmp_path / "module.py"
    source_file.write_text("def foo():\n    return 42\n", encoding="utf-8")
    result = _result("module.py", source_file, [_block(["def foo():"])])

    print_result_line(
        result,
        block=result["blocks"][0],
        line=1,
        color_enabled=True,
        vimgrep=False,
    )

    output = capsys.readouterr().out
    assert output.startswith("module.py:")
    assert "\x1b[1m1\x1b[0m:" in output  # bold line number
    assert "\x1b[" in output  # syntax-highlighted source


def test_display_results_plain_mode_prints_path_line_and_text(tmp_path, capsys):
    first_file = tmp_path / "first.py"
    first_file.write_text("line one\n", encoding="utf-8")
    second_file = tmp_path / "second.py"
    second_file.write_text("line two\n", encoding="utf-8")
    results = [
        _result("first.py", first_file, [_block(["line one"])]),
        _result("second.py", second_file, [_block(["line two"])]),
    ]

    display_results(results, max_results=None, color_enabled=False, vimgrep=False)

    assert capsys.readouterr().out == ("first.py:1:line one\nsecond.py:1:line two\n")


def test_display_results_vimgrep_mode_skips_empty_lines(tmp_path, capsys):
    source_file = tmp_path / "source.py"
    source_file.write_text("hello\n\nworld\n", encoding="utf-8")
    results = [_result("source.py", source_file, [_block(["hello", "", "world"])])]

    display_results(results, max_results=None, color_enabled=False, vimgrep=True)

    assert capsys.readouterr().out == "source.py:1:0:hello\nsource.py:3:0:world\n"


def test_display_results_can_colorize_without_bat_installed(tmp_path, capsys):
    source_file = tmp_path / "module.py"
    source_file.write_text("def foo():\n    return 42\n", encoding="utf-8")
    results = [
        _result("module.py", source_file, [_block(["def foo():", "    return 42"])])
    ]

    display_results(results, max_results=None, color_enabled=True, vimgrep=False)

    output = capsys.readouterr().out
    assert output.startswith("module.py:")
    assert "\x1b[1m1\x1b[0m:" in output
    assert "\x1b[" in output


def test_display_results_uses_bat_when_available(bat_available, bat_calls, tmp_path):
    first_file = tmp_path / "first.py"
    first_file.write_text("line one\n", encoding="utf-8")
    second_file = tmp_path / "second.py"
    second_file.write_text("line two\n", encoding="utf-8")
    results = [
        _result("first.py", first_file, [_block(["line one"])]),
        _result("second.py", second_file, [_block(["line two"])]),
    ]

    display_results(results, max_results=None, color_enabled=True, vimgrep=False)

    assert len(bat_calls) == 2
    assert bat_calls[0] == (
        f"bat {first_file} --file-name first.py --paging never --line-range 1:1"
    )
    assert bat_calls[1] == (
        f"bat {second_file} --file-name second.py --paging never --line-range 1:1"
    )


def test_display_results_with_bat_groups_blocks_of_the_same_file(
    bat_available, bat_calls, tmp_path
):
    source_file = tmp_path / "module.py"
    source_file.write_text("line one\nline two\nline three\n", encoding="utf-8")
    results = [
        _result(
            "module.py",
            source_file,
            [_block(["line one"]), _block(["line three"], start=3)],
        ),
    ]

    display_results(results, max_results=None, color_enabled=True, vimgrep=False)

    assert len(bat_calls) == 1
    assert bat_calls[0] == (
        f"bat {source_file} --file-name module.py --paging never "
        "--line-range 1:1 --line-range 3:3"
    )


def test_display_results_does_not_call_bat_without_results(bat_available, bat_calls):
    display_results([], max_results=None, color_enabled=True, vimgrep=False)

    assert bat_calls == []


def test_display_results_stops_after_max_results(tmp_path, capsys):
    results = []
    for index in range(1, 4):
        source_file = tmp_path / f"file{index}.py"
        source_file.write_text(f"line {index}\n", encoding="utf-8")
        results.append(
            _result(f"file{index}.py", source_file, [_block([f"line {index}"])])
        )

    display_results(results, max_results=2, color_enabled=False, vimgrep=False)

    assert capsys.readouterr().out == "file1.py:1:line 1\nfile2.py:1:line 2\n"


def test_display_results_with_bat_stops_after_max_results(
    bat_available, bat_calls, tmp_path
):
    results = []
    for index in range(1, 4):
        source_file = tmp_path / f"file{index}.py"
        source_file.write_text(f"line {index}\n", encoding="utf-8")
        results.append(
            _result(f"file{index}.py", source_file, [_block([f"line {index}"])])
        )

    display_results(results, max_results=2, color_enabled=True, vimgrep=False)

    assert len(bat_calls) == 2


def test_display_results_within_file_prefers_lower_score_block_over_line_order(
    tmp_path, capsys
):
    source_file = tmp_path / "module.py"
    source_file.write_text(
        "first line\nsecond line\nthird line\nfourth line\nfifth line\nsixth line\n",
        encoding="utf-8",
    )
    # An earlier block with a bad (high) score and a later block with a good
    # (low) score. With a budget that fits only one block, the later block is
    # chosen because its score is better.
    results = [
        _result(
            "module.py",
            source_file,
            [
                _block(["first line", "second line", "third line"], start=1, score=0.8),
                _block(["fourth line", "fifth line", "sixth line"], start=4, score=0.2),
            ],
        ),
    ]

    display_results(results, max_results=3, color_enabled=False, vimgrep=False)

    assert capsys.readouterr().out == (
        "module.py:4:fourth line\nmodule.py:5:fifth line\nmodule.py:6:sixth line\n"
    )


def test_display_results_yields_chosen_blocks_in_line_order(tmp_path, capsys):
    source_file = tmp_path / "module.py"
    source_file.write_text(
        "line one\nline two\nline three\nline four\nline five\nline six\n",
        encoding="utf-8",
    )
    # Three blocks; the budget fits all of them, but they are yielded in line
    # order even though they were chosen in score order.
    results = [
        _result(
            "module.py",
            source_file,
            [
                _block(["line one", "line two"], start=1, score=0.9),
                _block(["line three", "line four"], start=3, score=0.1),
                _block(["line five", "line six"], start=5, score=0.5),
            ],
        ),
    ]

    display_results(results, max_results=6, color_enabled=False, vimgrep=False)

    assert capsys.readouterr().out == (
        "module.py:1:line one\nmodule.py:2:line two\n"
        "module.py:3:line three\nmodule.py:4:line four\n"
        "module.py:5:line five\nmodule.py:6:line six\n"
    )


def test_display_results_within_file_takes_best_blocks_fitting_the_budget(
    tmp_path, capsys
):
    source_file = tmp_path / "module.py"
    source_file.write_text(
        "line one\nline two\nline three\nline four\nline five\nline six\n",
        encoding="utf-8",
    )
    # Budget of 3 lines: the best-scoring block (0.1) and the third-best (0.4)
    # fit, but the second-best (0.9) does not. The chosen blocks are yielded in
    # line order.
    results = [
        _result(
            "module.py",
            source_file,
            [
                _block(["line one", "line two"], start=1, score=0.9),
                _block(["line three"], start=3, score=0.1),
                _block(["line four", "line five"], start=4, score=0.4),
            ],
        ),
    ]

    display_results(results, max_results=3, color_enabled=False, vimgrep=False)

    assert capsys.readouterr().out == (
        "module.py:3:line three\nmodule.py:4:line four\nmodule.py:5:line five\n"
    )


def test_display_results_keeps_file_order_when_choosing_blocks(tmp_path, capsys):
    first_file = tmp_path / "first.py"
    first_file.write_text("line one\nline two\n", encoding="utf-8")
    second_file = tmp_path / "second.py"
    second_file.write_text("line three\nline four\n", encoding="utf-8")
    results = [
        _result("first.py", first_file, [_block(["line one"], start=1, score=0.9)]),
        _result(
            "second.py",
            second_file,
            [_block(["line three", "line four"], start=1, score=0.1)],
        ),
    ]

    display_results(results, max_results=2, color_enabled=False, vimgrep=False)

    # File order is kept: the first file is shown even though the second file
    # has the better-scoring block. The second file's block does not fit the
    # remaining budget, but a block is always printed in full (today's rule).
    assert capsys.readouterr().out == (
        "first.py:1:line one\nsecond.py:1:line three\nsecond.py:2:line four\n"
    )


def test_display_results_always_prints_at_least_one_block(tmp_path, capsys):
    source_file = tmp_path / "module.py"
    source_file.write_text("line one\n", encoding="utf-8")
    results = [
        _result("module.py", source_file, [_block(["line one"], start=1, score=0.2)]),
    ]

    display_results(results, max_results=0, color_enabled=False, vimgrep=False)

    assert capsys.readouterr().out == "module.py:1:line one\n"


# files -> blocks -> (score, number of result lines)
FILES_OF_BLOCKS = st.lists(
    st.lists(
        st.tuples(st.floats(0, 2, allow_nan=False), st.integers(1, 10)),
        min_size=1,
        max_size=6,
    ),
    min_size=1,
    max_size=4,
)


@given(files=FILES_OF_BLOCKS, max_results=st.none() | st.integers(0, 40))
def test_iterate_result_blocks_picks_best_blocks_and_keeps_line_order(
    files, max_results
):
    results = [
        _result(
            f"file{file_index}.py",
            f"/repo/file{file_index}.py",
            [
                # Blocks far apart, in line order
                _block(["x"] * line_count, start=block_index * 100 + 1, score=score)
                for block_index, (score, line_count) in enumerate(blocks)
            ],
        )
        for file_index, blocks in enumerate(files)
    ]

    printed = list(iterate_result_blocks(results, max_results))

    if max_results is None:
        assert printed == [
            (result, block) for result in results for block in result["blocks"]
        ]
        return

    assert printed, "at least one block is always printed"

    # Blocks are only added while the line budget is not used up: everything
    # but the last chosen block fits within max_results, so even without the
    # largest printed block the total stays under the budget
    printed_lines = [block["lineTypeCount"]["result"] for _, block in printed]
    if len(printed) > 1:
        assert sum(printed_lines) - max(printed_lines) < max_results

    printed_paths = list(dict.fromkeys(result["path"] for result, _ in printed))
    all_paths = [result["path"] for result in results]
    assert printed_paths == all_paths[: len(printed_paths)]

    for result in results:
        printed_blocks = [block for r, block in printed if r is result]
        if not printed_blocks:
            continue
        first_lines = [block["lines"][0]["line"] for block in printed_blocks]
        assert first_lines == sorted(first_lines)
        # Weak blocks never push out a strictly better block of the same file
        worst_printed = max(block["score"] for block in printed_blocks)
        for block in result["blocks"]:
            if all(block is not printed_block for printed_block in printed_blocks):
                assert block["score"] >= worst_printed
