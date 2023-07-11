from functools import cache
import os
import sys
import click
from pygments import highlight
from pygments.lexers import get_lexer_for_filename
from pygments.formatters import TerminalFormatter
from pygments.lexers.javascript import JavascriptLexer, TypeScriptLexer

from seagoat.engine import Engine


@cache
def get_highlighted_lines(file_name: str):
    with open(file_name, "r", encoding="utf-8") as source_code_file:
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


def print_result_line(result, line, color_enabled):
    if color_enabled:
        highlighted_lines = get_highlighted_lines(str(result.full_path))
        print(
            f"{result.path}:{click.style(str(line), bold=True)}:{highlighted_lines[line - 1]}"
        )
    else:
        print(f"{result.path}:{line}:{result.line_texts[line - 1]}")


@click.command()
@click.argument("query")
@click.argument("repo_path", required=False, default=os.getcwd())
@click.option("--no-color", is_flag=True)
def seagoat(query, repo_path, no_color):
    """Query your codebase using vector embeddings"""
    my_seagoat = Engine(repo_path)
    my_seagoat.analyze_codebase()

    my_seagoat.query(query)
    my_seagoat.fetch_sync()
    results = my_seagoat.get_results()

    color_enabled = sys.stdout.isatty() and not no_color
    for result in results:
        for line in result.get_lines(query):
            print_result_line(result, line, color_enabled)


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    seagoat()
