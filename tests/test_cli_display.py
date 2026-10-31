"""Behavioural tests for seagoat.utils.cli_display.

These cover how search results are printed to the terminal:
plain text, colored highlighted source, vimgrep format, and bat.
"""

from seagoat.utils.cli_display import (
    display_results,
    get_highlighted_lines,
    print_result_line,
)


def _block(lines, start=1):
    """A result block in the shape the server sends to the CLI."""
    return {
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
