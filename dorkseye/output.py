"""Save results as txt, json, jsonl or csv (picked from the file extension)."""

from __future__ import annotations

import csv
import json
import os
from typing import Iterable

from .engines import Result

FORMATS = ("txt", "json", "jsonl", "csv")


def detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext if ext in FORMATS else "txt"


def save(path: str, dork: str, results: Iterable[Result], fmt: str | None = None) -> str:
    """Append results for `dork` to `path`. Returns the path written."""
    fmt = fmt or detect_format(path)
    if fmt == "txt" and not os.path.splitext(path)[1]:
        path += ".txt"
    results = list(results)

    if fmt == "json":
        data = []
        if os.path.exists(path) and os.path.getsize(path):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        data.append({"dork": dork, "results": [r.to_dict() for r in results]})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    elif fmt == "jsonl":
        with open(path, "a", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({"dork": dork, **r.to_dict()}, ensure_ascii=False) + "\n")
    elif fmt == "csv":
        new = not os.path.exists(path) or not os.path.getsize(path)
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["dork", "engine", "url", "title", "snippet"])
            for r in results:
                w.writerow([dork, r.engine, r.url, r.title, r.snippet])
    else:
        with open(path, "a", encoding="utf-8") as fh:
            for r in results:
                fh.write(r.url + "\n")
    return path
