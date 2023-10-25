import json
from pathlib import Path

import click

from benchmark.utils import create_ai_persona, generate_personality


def evaluate_test_case_quality(repositories_path, ask_conversational_ai, example):
    try:
        with open(
            Path(repositories_path)
            / example["repo"]["name"]
            / example["targetCode"]["path"],
            encoding="utf-8",
        ) as input_file:
            lines = input_file.readlines()

        line_text = lines[example["targetCode"]["lineNumber"] + 1]

        evaluation_prompt = (
            [
                "You're tasked with evaluating the quality of test cases for an AI-based code search tool.",
                f"Repository Name: {example['repo']['name']}",
                f"Repository Description: {example['repo']['description']}",
                f"Target File Path: {example['targetCode']['path']}",
                f"Target Line Number: {example['targetCode']['lineNumber']}",
                f"Content of the Target Code Line: '{line_text}'",
                "Here are the queries of this test case:",
                "",
            ]
            + example["queries"]
            + [
                "",
                "Consider the following criteria:",
                "- How specific are the queries? Are they too broad, overly verbose, or do they focus on unique aspects of the code?",
                "- Does the combination of file path and target line number provide context to aid the search?",
                "- How well do the queries describe or reference the actual content of the target code line, even if they don't match the exact words? Do they use synonyms or descriptive terms that convey the same meaning?",
                "- A quality query doesn't necessarily have to use the exact terms found in the code line but should be able to describe it using synonyms or equivalent concepts.",
                "Based on these criteria, rate the test case's quality on a scale from 0 to 100, where 100 is the highest quality.",
                "After your reasoning, please include a line just with five equal signs (=====), and then a final line just with the single number and nothing else!",
            ]
        )

        quality_score = ask_conversational_ai(evaluation_prompt)["text"]

        return int(float(quality_score.split("=====")[1].strip()))
    except (ValueError, IndexError, RuntimeError) as error:
        click.echo(f"Error! {error}")
        return None


@click.command()
@click.argument(
    "repositories_path",
    type=click.Path(exists=True, dir_okay=True, file_okay=False),
)
@click.argument("api_key", type=str)
def evaluate_testcases(repositories_path, api_key):
    ask_conversational_ai = create_ai_persona(generate_personality(), api_key)
    examples_path = Path(__file__).parent / "examples"

    if not examples_path.exists():
        return

    example_folders = [f for f in examples_path.iterdir() if f.is_dir()]

    for example_folder in example_folders:
        example_file = Path(example_folder) / "example.json"
        with open(example_file, encoding="utf-8") as file:
            example_data = json.load(file)

            if "qualityScore" not in example_data:
                quality_scores = [
                    evaluate_test_case_quality(
                        repositories_path, ask_conversational_ai, example_data
                    )
                    for _ in range(3)
                ]
                quality_score = int(
                    sum(x for x in quality_scores if x is not None)
                    / len(quality_scores)
                )

                if 0 <= quality_score <= 100:
                    example_data["qualityScore"] = quality_score
                else:
                    continue

                with open(example_file, "w", encoding="utf-8") as file:
                    json.dump(example_data, file, indent=4)

            else:
                pass


if __name__ == "__main__":
    evaluate_testcases()
