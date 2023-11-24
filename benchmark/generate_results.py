import collections
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
from pathlib import Path

import click


def generate_random_results(repo_dir, _, __):
    command = r"""git grep -n --full-name '' -- '*\.rs' '*\.go' '*\.cpp' '*\.c' '*\.h' '*\.ts' '*\.js' '*\.jsx' '*\.tsx' '*\.py' | shuf -n 500"""

    results = subprocess.check_output(command, shell=True, text=True, cwd=repo_dir)
    return results


def generate_seagoat_results(repo_dir, query_text, seagoat_args):
    query_text = query_text.replace("'", "'\\''")
    return subprocess.check_output(
        f"poetry run gt --no-color {seagoat_args} '{query_text}' {repo_dir}",
        shell=True,
    ).decode("utf-8")


RESULT_TYPE_FUNCTIONS = {
    "random": generate_random_results,
    "seagoat": generate_seagoat_results,
}


def process_example(example, examples_path, repo_folder, test_run_name, seagoat_args):
    example_description = f"{example['repo']['name']}:{example['targetCode']['path']}:{example['targetCode']['lineNumber']}"
    click.echo(f"Processing {example_description}")

    results_folder = examples_path / example["uuid"] / "results" / test_run_name
    results_folder.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_query = {
            executor.submit(
                process_query, query, index, results_folder, repo_folder, seagoat_args
            ): query
            for index, query in enumerate(example["queries"])
        }
        for future in future_to_query:
            future.result()


def process_query(query, index, results_folder, repo_folder, seagoat_args):
    query_results_folder = results_folder / str(index)
    query_results_folder.mkdir(parents=True, exist_ok=True)

    for result_type, result_type_function in RESULT_TYPE_FUNCTIONS.items():
        result_type_results_file = query_results_folder / f"{result_type}.txt"
        if result_type_results_file.exists():
            continue

        with open(result_type_results_file, "w", encoding="utf-8") as output_file:
            output_file.write(result_type_function(repo_folder, query, seagoat_args))


@click.command()
@click.argument("test_run_name", type=str)
@click.argument(
    "repositories_path",
    type=click.Path(exists=True, dir_okay=True, file_okay=False),
)
@click.option(
    "--seagoat-args",
    default="",
    type=str,
    help="Extra arguments to pass to SeaGOAT",
)
def generate_results(test_run_name, repositories_path, seagoat_args):
    examples_path = Path(__file__).parent / "examples"

    if not examples_path.exists():
        return

    subfolders = [f for f in examples_path.iterdir() if f.is_dir()]

    examples_grouped_by_project = collections.defaultdict(list)

    for subfolder in subfolders:
        with open(subfolder / "example.json", encoding="utf-8") as input_file:
            example = json.load(input_file)
            examples_grouped_by_project[example["repo"]["name"]].append(example)

    for repo_name, examples in examples_grouped_by_project.items():
        repo_folder = Path(repositories_path) / repo_name
        click.echo(repo_folder)
        for example in examples:
            process_example(
                example,
                examples_path,
                repo_folder,
                test_run_name,
                seagoat_args,
            )


if __name__ == "__main__":
    generate_results()
