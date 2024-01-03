import math
import subprocess
from functools import cache
from typing import Optional

import click


@cache
def get_highlighted_lines(file_name: str):
    from pygments import highlight
    from pygments.formatters import TerminalFormatter
    from pygments.lexers import get_lexer_for_filename
    from pygments.lexers.javascript import JavascriptLexer, TypeScriptLexer

    with open(file_name, encoding="utf-8") as source_code_file:
        code = source_code_file.read()

    if file_name.endswith(".md"):
        return code.splitlines()

    if file_name.endswith(".jsx"):
        lexer = JavascriptLexer()
    elif file_name.endswith(".tsx"):
        lexer = TypeScriptLexer()
    else:
        lexer = get_lexer_for_filename(file_name)

    result = highlight(code, lexer, TerminalFormatter())

    return result.splitlines()


def print_result_line(result, block, line, color_enabled, vimgrep):
    if color_enabled:
        highlighted_lines = get_highlighted_lines(str(result["fullPath"]))
        click.echo(
            f"{result['path']}:{click.style(str(line), bold=True)}:{highlighted_lines[line - 1]}",
            color=True,
        )
    else:
        for line_content in block["lines"]:
            if line_content["line"] == line:
                if vimgrep:
                    click.echo(f"{result['path']}:{line}:0:{line_content['lineText']}")
                else:
                    click.echo(f"{result['path']}:{line}:{line_content['lineText']}")
                break


def iterate_result_blocks(results, max_results: Optional[int]):
    lines_left_to_print = max_results if max_results is not None else math.inf
    number_of_blocks_printed = 0

    for result in results:
        for block in result["blocks"]:
            if lines_left_to_print <= 0 and number_of_blocks_printed >= 1:
                return

            lines_left_to_print -= block["lineTypeCount"]["result"]

            yield result, block

            number_of_blocks_printed += 1


def display_results_using_bat(results, max_results):
    if not results:
        return

    current_result = None
    blocks = []

    for result, block in iterate_result_blocks(results, max_results):
        if current_result is None:
            current_result = result

        if result["path"] != current_result["path"]:
            display_blocks_with_bat(current_result, blocks)
            current_result = result
            blocks = []

        blocks.append(block)

    display_blocks_with_bat(current_result, blocks)


def display_results(results, max_results, color_enabled, vimgrep):
    if color_enabled and is_bat_installed():
        display_results_using_bat(results, max_results)
        return

    for result, block in iterate_result_blocks(results, max_results):
        print_result_block(result, block, color_enabled, vimgrep)


def is_bat_installed():
    try:
        result = subprocess.run(
            ["bat", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def display_blocks_with_bat(result, blocks):
    file_name = result["path"]
    full_path = result["fullPath"]

    command = [
        "bat",
        full_path,
        "--file-name",
        file_name,
        "--paging",
        "never",
    ]

    for block in blocks:
        start_line_number = block["lines"][0]["line"]
        end_line_number = block["lines"][-1]["line"]
        command.extend(["--line-range", f"{start_line_number}:{end_line_number}"])

    subprocess.run(command, check=True)


def print_result_block(result, block, color_enabled, vimgrep):
    for result_line in block["lines"]:
        line = result_line["line"]
        print_result_line(result, block, line, color_enabled, vimgrep)
