# pylint: disable=too-few-public-methods

import os
import re

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.validation import Validator
from blessed import Terminal
from pygments import highlight
from pygments.lexers import get_lexer_for_filename
from pygments.formatters import TerminalFormatter
from pygments.lexers.javascript import JavascriptLexer, TypeScriptLexer

from engine import Engine


def get_highlighted_lines(file_name: str):
    with open(file_name, "r", encoding="utf-8") as source_code_file:
        code = source_code_file.read()

    if file_name.endswith(".jsx"):
        lexer = JavascriptLexer()
    elif file_name.endswith(".tsx"):
        lexer = TypeScriptLexer()
    else:
        lexer = get_lexer_for_filename(file_name)

    result = highlight(code, lexer, TerminalFormatter())

    return result.splitlines()


class RealTimeValidator(Validator):
    def __init__(self, term, engine):
        self.term = term
        self.engine = engine
        self._icon_map = {
            ".txt": ("\uF15C", self.term.white),
            ".md": ("\uF48A", self.term.cyan),
            ".py": ("\uE73C", self.term.green),
            ".c": ("\uE61E", self.term.yellow),
            ".cpp": ("\uE61D", self.term.yellow),
            ".h": ("\uF0FD", self.term.yellow),
            ".hpp": ("\uF0FD", self.term.yellow),
            ".ts": ("\uE628", self.term.blue),
            ".js": ("\uE74E", self.term.blue),
            ".tsx": ("\uF48A", self.term.blue),
            ".jsx": ("\uF48A", self.term.blue),
            ".html": ("\uE736", self.term.red),
        }
        self.lines_already_printed = 0

    def get_icon_for_file(self, file_name):
        _, ext = os.path.splitext(file_name)
        fallback_icon = self._icon_map[".txt"]
        icon, color = self._icon_map.get(ext, fallback_icon)
        return color(icon)

    def _print(self, text: str, *args, **kwargs):
        if self.lines_already_printed >= self.term.height:
            return
        self.lines_already_printed += 1
        ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
        stripped = ansi_escape.sub("", text)

        if len(stripped) <= self.term.width:
            print(text, *args, **kwargs)

        else:
            remaining = text

            while len(ansi_escape.sub("", remaining)) > self.term.width:
                remaining = remaining.rsplit("\x1b", 1)[0]

            reset_sequence = "\x1b[0m"
            print(remaining + reset_sequence, *args, **kwargs)

    def validate(self, document):
        with self.term.location():
            query_text = document.text
            print(self.term.move_xy(0, 0) + self.term.clear_eol(), end="")
            self._print(query_text, end="")
            print(self.term.move_xy(0, 1) + self.term.clear_eos(), end="")
            self.lines_already_printed = 1
            if query_text:
                self.engine.query(query_text)
                self.engine.fetch_sync()
                results = self.engine.get_results()

                if not results:
                    return

                max_line_number_length = len(
                    str(max(max(result.get_lines(query_text)) for result in results))
                )

                for result in results:
                    self._print(f"{self.get_icon_for_file(result.path)} {result.path}")
                    formatted_lines = get_highlighted_lines(str(result.full_path))
                    previous_line = None
                    for line in sorted(result.get_lines(query_text)):
                        left_sign = "│ "
                        if previous_line != line - 1:
                            left_sign = "├─"
                        previous_line = line
                        left_sign = self.term.color(8)(left_sign)
                        formatted_line_number = self.term.on_color(8)(
                            (str(line)).rjust(max_line_number_length)
                        )

                        self._print(
                            f"{left_sign}{formatted_line_number}{formatted_lines[line - 1]}"
                        )
                    print()
                    print()


@click.command()
@click.argument("repo_path")
@click.argument("query", required=False)
def analyze_codebase(repo_path, query):
    """Query your codebase using vector embeddings"""
    my_codector = Engine(repo_path)
    my_codector.analyze_codebase()

    if query is not None:
        my_codector.query(query)
        my_codector.fetch_sync()
        results = my_codector.get_results()

        for result in results:
            for line in result.get_lines(query):
                print(f"{result.path}:{line}:{result.line_texts[line - 1]}")

        return

    term = Terminal()
    with term.fullscreen():
        print("Query: ", end="")
        session = PromptSession(validator=RealTimeValidator(term, my_codector))
        try:
            session.prompt()
        except EOFError:
            pass


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    analyze_codebase()
