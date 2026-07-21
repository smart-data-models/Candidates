#!/usr/bin/env python3
"""
Generate standards-index.json and docs/index-data.json from the standards/
directory tree, for the front-end search page in docs/index.html.

Usage:
    python3 tools/generate_index.py

Run from anywhere inside the repo; paths are resolved relative to this
script's location so it also works unattended in CI (see
.github/workflows/build-index.yml).
"""
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STANDARDS_DIR = os.path.join(REPO_ROOT, "standards")
OUTPUT_PATHS = [
    os.path.join(REPO_ROOT, "standards-index.json"),
    os.path.join(REPO_ROOT, "docs", "index-data.json"),
]


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_index():
    entries = []
    if not os.path.isdir(STANDARDS_DIR):
        return entries

    for slug in sorted(os.listdir(STANDARDS_DIR)):
        standard_dir = os.path.join(STANDARDS_DIR, slug)
        meta_path = os.path.join(standard_dir, "standard-metadata.yaml")
        models_dir = os.path.join(standard_dir, "models")
        if not os.path.isdir(models_dir):
            continue

        meta = load_yaml(meta_path) if os.path.isfile(meta_path) else {}

        models = []
        for entity in sorted(os.listdir(models_dir)):
            schema_path = os.path.join(models_dir, entity, "schema.json")
            if not os.path.isfile(schema_path):
                continue
            try:
                schema = load_json(schema_path)
            except Exception as e:
                print(f"WARNING: could not parse {schema_path}: {e}", file=sys.stderr)
                schema = {}
            models.append({
                "name": entity,
                "title": schema.get("title", entity),
                "description": schema.get("description", ""),
                "schemaUrl": f"https://raw.githubusercontent.com/smart-data-models/Candidates/master/standards/{slug}/models/{entity}/schema.json",
                "githubUrl": f"https://github.com/smart-data-models/Candidates/tree/master/standards/{slug}/models/{entity}",
            })

        if not models:
            continue

        entries.append({
            "slug": slug,
            "title": meta.get("title", slug),
            "description": meta.get("description", "").strip() if isinstance(meta.get("description"), str) else "",
            "publisher": meta.get("publisher", ""),
            "sourceUrl": meta.get("sourceUrl", ""),
            "license": meta.get("license", ""),
            "domains": meta.get("domains", []),
            "modelCount": len(models),
            "models": models,
            "githubUrl": f"https://github.com/smart-data-models/Candidates/tree/master/standards/{slug}",
        })

    return entries


def main():
    index = build_index()
    payload = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    for path in OUTPUT_PATHS:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"Written: {path} ({len(index)} standards, "
              f"{sum(e['modelCount'] for e in index)} models)")


if __name__ == "__main__":
    main()
