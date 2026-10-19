import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def load():
    with (DATA / "catalogue.json").open() as f:
        return json.load(f)


def zones():
    with (DATA / "zones.json").open() as f:
        return json.load(f)
