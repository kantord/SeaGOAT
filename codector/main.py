import click
from engine import Engine


@click.command()
@click.argument("repo_path")
def analyze_codebase(repo_path):
    """Analyze a codebase and print the top files"""
    my_codector = Engine(repo_path)
    my_codector.analyze_codebase()
    for file in my_codector.repository.top_files()[:1000]:
        print(file)


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    analyze_codebase()
