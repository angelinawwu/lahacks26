"""
Utility script: re-generate or inspect the seed JSON files.

Run directly to print a summary of what is loaded:
  python backend/data/seed.py
"""
from __future__ import annotations

import json
import os
import sys

DATA_DIR = os.path.dirname(__file__)


def load_all() -> dict:
    result = {}
    for name in ("doctors", "nurses", "patients", "rooms", "ehr"):
        path = os.path.join(DATA_DIR, f"{name}.json")
        with open(path, encoding="utf-8") as fh:
            result[name] = json.load(fh)
    return result


if __name__ == "__main__":
    data = load_all()
    for key, value in data.items():
        count = len(value) if isinstance(value, (list, dict)) else "?"
        print(f"{key:>10}: {count} records")
