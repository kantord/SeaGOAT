import json
import random

import requests

# These are benchmark utils. Please don't use in production code.


def generate_personality():
    names = [
        "John",
        "Sofia",
        "Aisha",
        "Ananya",
        "Chen",
        "Maria",
        "Tariq",
        "Siti",
        "Oliver",
        "Ekaterina",
        "Chioma",
        "Ngozi",
        "Sho",
        "Jasmine",
        "Carlos",
    ]
    roles = [
        "Junior Developer",
        "Senior Developer",
        "Team Lead",
        "Frontend Developer",
        "Backend Developer",
        "Full Stack Developer",
        "Developer Advocate",
        "QA Engineer",
        "Developer Temporarily Helping with the Project",
        "Systems Architect",
        "Database Administrator",
        "Product Manager",
        "Technical Writer",
        "DevOps Engineer",
    ]
    traits = [
        "happy",
        "angry",
        "helpful",
        "tired",
        "knowledgeable",
        "curious",
        "optimistic",
        "pessimistic",
        "meticulous",
        "laid-back",
        "pragmatic",
        "in a hurry",
    ]
    editors = ["jetbrains", "vim", "neovim", "vscode"]

    selected_name = random.choice(names)
    selected_role = random.choice(roles)
    selected_editor = random.choice(editors)
    selected_traits = random.sample(traits, 2)

    return f"You are {selected_name}, a {selected_role} who is often {selected_traits[0]} and {selected_traits[1]}. You are a {selected_editor} user."


def create_ai_persona(system_role, api_key, model="gpt-3.5-turbo"):
    def query(prompt_lines, schema=None, function_name=None):
        prompt = "\n".join(prompt_lines)
        if schema and not function_name:
            raise ValueError("Function name is required when schema is provided")

        if len(prompt.split()) > 2800:
            raise ValueError("Prompt is too long!")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_role},
                {"role": "user", "content": prompt},
            ],
        }

        if schema:
            data["functions"] = [{"name": function_name, "parameters": schema}]
            data["function_call"] = {"name": function_name}

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            data=json.dumps(data),
        )

        if response.status_code == 200:
            if schema:
                return response.json()["choices"][0]["message"]["function_call"][
                    "arguments"
                ]

            return {"text": response.json()["choices"][0]["message"]["content"]}

        raise RuntimeError(f"Error {response.status_code}: {response.text}")

    return query
