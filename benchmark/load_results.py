import json
from pathlib import Path


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


def load_results():
    examples_path = Path(__file__).parent / "examples"
    subfolders = [f for f in examples_path.iterdir() if f.is_dir()]
    results = []

    for subfolder in subfolders:
        with open(subfolder / "example.json", encoding="utf-8") as input_file:
            example = json.load(input_file)
            queries = example["queries"]

            queries_with_results = []

            for index, query in enumerate(queries):
                query_results = {}
                for result_type in ["random", "seagoat"]:
                    query_results_folder = subfolder / "results" / str(index)
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
