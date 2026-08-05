import json
import yaml


def load_yaml(path):

    with open(path, "r", encoding="utf-8") as file:

        return yaml.safe_load(file)


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)