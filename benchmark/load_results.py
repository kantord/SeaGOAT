import json
from pathlib import Path

from yaml import dump
from yaml import load

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

MAXIMUM_NUMBER_OF_RESULT_LINES = 500


def get_list_of_test_runs() -> list:
    script_dir = Path(__file__).parent
    root = script_dir / "examples"

    test_runs = set()

    for child in root.iterdir():
        if child.is_dir():
            results_dir = child / "results"
            if results_dir.exists():
                for run_name in results_dir.iterdir():
                    if run_name.is_dir():
                        test_runs.add(run_name.name)

    return sorted(list(test_runs))


def evaluate_results(file_contents, example):
    lines = file_contents.split("\n")

    for line in lines:
        if not line:
            continue

        split_line = line.split(":")
        path = split_line[0]
        line_number = int(split_line[1])
        if (
            path == example["targetCode"]["path"]
            and line_number == example["targetCode"]["lineNumber"]
        ):
            return int(line_number)

    return None


def create_result_summary(test_run):
    subfolders = [
        f for f in (Path(__file__).parent / "examples").iterdir() if f.is_dir()
    ]
    results = []

    for subfolder in subfolders:
        with open(subfolder / "example.json", encoding="utf-8") as input_file:
            example = json.load(input_file)
            queries = example["queries"]

            queries_with_results = []

            for index, query in enumerate(queries):
                query_results = {}
                for result_type in ["random", "seagoat"]:
                    query_results_folder = subfolder / "results" / test_run / str(index)
                    result_type_results_file = (
                        query_results_folder / f"{result_type}.txt"
                    )
                    with open(result_type_results_file, encoding="utf-8") as input_file:
                        file_contents = input_file.read()
                        query_results[result_type] = evaluate_results(
                            file_contents, example
                        )

                queries_with_results.append(
                    {
                        "text": query,
                        "positionOfCorrectResult": query_results,
                    }
                )

            results.append(
                {
                    **example,
                    "queries": queries_with_results,
                }
            )

    return results


def get_results_yaml_folder():
    results_folder = Path(__file__).parent / "results"
    results_folder.mkdir(parents=True, exist_ok=True)

    return results_folder


def get_results_yaml_file_path(test_run):
    return get_results_yaml_folder() / f"{test_run}.yaml"


def create_result_summary_yaml(test_run):
    with open(
        get_results_yaml_file_path(test_run), "w", encoding="utf-8"
    ) as output_file:
        output_file.write(dump(create_result_summary(test_run), Dumper=Dumper))


def load_results(test_run):
    if not get_results_yaml_file_path(test_run).exists():
        create_result_summary_yaml(test_run)

    with open(get_results_yaml_file_path(test_run), encoding="utf-8") as input_file:
        return load(input_file, Loader=Loader)


def get_percentage_of_queries_with_correct_results(results, engine):
    total_queries = 0
    correct_results = 0

    for example in results:
        for query in example["queries"]:
            total_queries += 1
            if query["positionOfCorrectResult"][engine] is not None:
                correct_results += 1

    return float(correct_results) / total_queries * 100


def get_percentage_of_examples_with_correct_results(results, engine):
    total_examples = 0
    correct_results = 0

    for example in results:
        total_examples += 1
        for query in example["queries"]:
            if query["positionOfCorrectResult"][engine] is not None:
                correct_results += 1
                break

    return float(correct_results) / total_examples * 100


def get_positions_of_correct_results(results, engine):
    positions = []

    for example in results:
        for query in example["queries"]:
            position = query["positionOfCorrectResult"][engine]
            if position is not None:
                positions.append(position)

    return positions


def get_best_position_of_correct_results(results, engine):
    positions = []

    for example in results:
        positions_for_example = []
        for query in example["queries"]:
            position = query["positionOfCorrectResult"][engine]
            if position is not None:
                positions_for_example.append(position)

        if positions_for_example:
            positions.append(min(positions_for_example))

    return positions


def get_average_position_of_a_correct_results(results, engine):
    positions = get_positions_of_correct_results(results, engine)

    if not positions:
        return None

    return sum(positions) / len(positions)


def get_chance_of_getting_correct_result_in_n_lines(results, engine):
    positions = {(index + 1): 0 for index in range(MAXIMUM_NUMBER_OF_RESULT_LINES)}
    total_queries = 0

    for example in results:
        for query in example["queries"]:
            total_queries += 1
            position = query["positionOfCorrectResult"][engine]

            if position is None:
                continue

            for index in range(position, MAXIMUM_NUMBER_OF_RESULT_LINES + 1):
                positions[index] += 1

    return [
        float(positions[index + 1]) / total_queries * 100
        for index in range(MAXIMUM_NUMBER_OF_RESULT_LINES)
    ]
