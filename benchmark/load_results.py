import statistics
import collections
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from yaml import dump, load

try:
    from yaml import CDumper as Dumper
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Dumper, Loader

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


def get_percentage_of_queries_with_correct_results(row):
    total_queries = 0
    correct_results = 0

    for example in row["Data"]:
        for query in example["queries"]:
            total_queries += 1
            if query["positionOfCorrectResult"][row["Engine"]] is not None:
                correct_results += 1

    return float(correct_results) / total_queries


def get_percentage_of_examples_with_correct_results(row):
    total_examples = 0
    correct_results = 0

    for example in row["Data"]:
        total_examples += 1
        for query in example["queries"]:
            if query["positionOfCorrectResult"][row["Engine"]] is not None:
                correct_results += 1
                break

    return float(correct_results) / total_examples


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


def get_average_position_of_a_correct_results(row):
    positions = get_positions_of_correct_results(row["Data"], row["Engine"])

    if not positions:
        return None

    return sum(positions) / len(positions)


def get_median_position_of_a_correct_results(row):
    positions = get_positions_of_correct_results(row["Data"], row["Engine"])

    if not positions:
        return None

    return statistics.median(positions)


def get_chance_of_getting_correct_result_in_n_lines(all_results, category_map):
    positions = collections.defaultdict(
        lambda: {(index + 1): 0 for index in range(MAXIMUM_NUMBER_OF_RESULT_LINES)}
    )
    total_queries = collections.defaultdict(lambda: 0)

    for test_run, results, engine in all_results:
        for example in results:
            for query in example["queries"]:
                category_name = category_map(test_run, query, engine, example)
                total_queries[category_name] += 1
                position = query["positionOfCorrectResult"][engine]

                if position is None:
                    continue

                for index in range(position, MAXIMUM_NUMBER_OF_RESULT_LINES + 1):
                    positions[category_name][index] += 1

    category_names = list(total_queries.keys())
    return [
        [
            [
                float(positions[category_name][index + 1])
                / total_queries[category_name]
                for index in range(MAXIMUM_NUMBER_OF_RESULT_LINES)
            ]
            for category_name in category_names
        ],
        category_names,
        [(index + 1) for index in range(MAXIMUM_NUMBER_OF_RESULT_LINES)],
    ]


def plot_chance_of_getting_correct_result_in_n_lines(all_results, category_map):
    y_axes, labels, x_axis = get_chance_of_getting_correct_result_in_n_lines(
        all_results, category_map
    )
    for y_axis, label in zip(y_axes, labels):
        plt.plot(x_axis, y_axis, label=label)
    plt.legend()
    plt.xlabel("Position in result list")
    plt.ylabel("Chance of the correct result")
    plt.gca().yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    plt.show()


def filter_minimum_example_quality(results, minimum_example_quality):
    return [
        result
        for result in results
        if result["qualityScore"] >= minimum_example_quality
    ]


def load_results_for_all_runs(minimum_example_quality):
    list_of_test_runs = get_list_of_test_runs()
    results = [
        ("random", load_results(list_of_test_runs[0]), "random"),
        (list_of_test_runs[0], load_results(list_of_test_runs[0]), "seagoat"),
    ]

    for test_run in list_of_test_runs[1:]:
        results.append((test_run, load_results(test_run), "seagoat"))

    return [
        [
            test_run_name,
            filter_minimum_example_quality(results, minimum_example_quality),
            engine,
        ]
        for test_run_name, results, engine in results
    ]


def get_list_of_projects():
    list_of_test_runs = get_list_of_test_runs()
    projects = set()

    for example in load_results(list_of_test_runs[0]):
        projects.add(example["repo"]["name"])

    return sorted(list(projects))


def iterate_queries(results):
    for example in results:
        for query in example["queries"]:
            yield {**example, **query}
