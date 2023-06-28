# pylint: disable=too-few-public-methods

import click
from engine import Engine
from prompt_toolkit import PromptSession
from prompt_toolkit.validation import Validator
from blessed import Terminal


class RealTimeValidator(Validator):
    def __init__(self, term):
        self.term = term

    def validate(self, document):
        current_text = document.text
        print(self.term.move_xy(0, 0) + self.term.clear_eol(), end="")
        print(f"Query: {current_text}", end="")
        print(self.term.move_xy(0, 2) + self.term.clear_eos(), end="")
        if current_text:
            print(f"mock results for '{current_text}', blah blah", end="")


@click.command()
@click.argument("repo_path")
def analyze_codebase(repo_path):
    """Query your codebase using vector embeddings"""
    my_codector = Engine(repo_path)
    my_codector.analyze_codebase()

    term = Terminal()
    with term.fullscreen():
        print("Query: ", end="")
        session = PromptSession(validator=RealTimeValidator(term))
        try:
            session.prompt()
        except EOFError:
            pass


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    analyze_codebase()
