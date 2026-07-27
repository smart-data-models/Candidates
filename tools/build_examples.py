#!/usr/bin/env python3
"""
Derive the three non-canonical example formats from a model's example.json.

Every Candidates model must ship four example files, all serializations of
the *same* entity instance:

    examples/example.json               NGSIv2 key-values   (canonical source)
    examples/example.jsonld             NGSI-LD key-values  (= example.json + @context)
    examples/example-normalized.json    NGSIv2 normalized   (type: Text/Number/Boolean/
                                                               DateTime/StructuredValue/URL)
    examples/example-normalized.jsonld  NGSI-LD normalized  (type: Property/Relationship/
                                                               GeoProperty)

example.json is treated as the single source of truth; this script derives
the other three from it plus the model's schema.json (for date/date-time
formats) and its own context.jsonld (for the @context URL). Re-run any time
example.json changes, to keep the other three in sync.

Usage:
    python3 tools/build_examples.py standards/<slug>/models/<Entity>
    python3 tools/build_examples.py --all           # every model in standards/

@context is emitted as an array (e.g. ["https://.../context.jsonld"]), per
the smart-data-models convention.
"""
import argparse
import collections
import glob
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEXT_BASE = "https://raw.githubusercontent.com/smart-data-models/Candidates/master"


def is_relationship_value(value):
    """A Relationship in this repo's examples is always a URI string, or an
    array of URI strings -- urn:ngsi-ld:... or http(s)://..."""
    def looks_like_uri(v):
        return isinstance(v, str) and (v.startswith("urn:ngsi-ld:") or v.startswith("http"))
    if looks_like_uri(value):
        return True
    if isinstance(value, list) and value and all(looks_like_uri(v) for v in value):
        return True
    return False


def ngsild_normalized_value(key, value, prop_schema):
    if key == "location" or (isinstance(value, dict) and value.get("type") == "Point"):
        return collections.OrderedDict([("type", "GeoProperty"), ("value", value)])
    if is_relationship_value(value):
        return collections.OrderedDict([("type", "Relationship"), ("object", value)])
    return collections.OrderedDict([("type", "Property"), ("value", value)])


def ngsiv2_type(key, value, prop_schema):
    if is_relationship_value(value):
        return "URL"
    fmt = (prop_schema or {}).get("format")
    if fmt in ("date", "date-time"):
        return "DateTime"
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, (int, float)):
        return "Number"
    if isinstance(value, (dict, list)):
        return "StructuredValue"
    return "Text"


def build_keyvalues_jsonld(example, context_url):
    out = collections.OrderedDict(example)
    out["@context"] = [context_url]
    return out


def build_normalized_v2(example, schema_props):
    out = collections.OrderedDict()
    for k, v in example.items():
        if k in ("id", "type"):
            out[k] = v
            continue
        out[k] = collections.OrderedDict([
            ("type", ngsiv2_type(k, v, schema_props.get(k))),
            ("value", v),
        ])
    return out


def build_normalized_ld(example, schema_props, context_url):
    out = collections.OrderedDict()
    for k, v in example.items():
        if k in ("id", "type"):
            out[k] = v
            continue
        out[k] = ngsild_normalized_value(k, v, schema_props.get(k))
    out["@context"] = [context_url]
    return out


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("Written:", os.path.relpath(path, REPO_ROOT))


def context_url_for(model_dir):
    rel = os.path.relpath(model_dir, REPO_ROOT)
    return f"{CONTEXT_BASE}/{rel}/context.jsonld"


def process_model(model_dir):
    example_path = os.path.join(model_dir, "examples", "example.json")
    schema_path = os.path.join(model_dir, "schema.json")
    if not os.path.isfile(example_path) or not os.path.isfile(schema_path):
        print(f"SKIP {model_dir}: missing schema.json or examples/example.json")
        return

    example = json.load(open(example_path), object_pairs_hook=collections.OrderedDict)
    schema = json.load(open(schema_path))
    schema_props = schema.get("properties", {})
    ctx_url = context_url_for(model_dir)

    write(os.path.join(model_dir, "examples", "example.jsonld"),
          build_keyvalues_jsonld(example, ctx_url))
    write(os.path.join(model_dir, "examples", "example-normalized.json"),
          build_normalized_v2(example, schema_props))
    write(os.path.join(model_dir, "examples", "example-normalized.jsonld"),
          build_normalized_ld(example, schema_props, ctx_url))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model_dir", nargs="?", help="path to a models/<Entity> directory")
    ap.add_argument("--all", action="store_true", help="process every model under standards/")
    args = ap.parse_args()

    if args.all:
        model_dirs = sorted(glob.glob(os.path.join(REPO_ROOT, "standards", "*", "models", "*")))
        if not model_dirs:
            print("No models found under standards/*/models/*")
            return
        for d in model_dirs:
            process_model(d)
    elif args.model_dir:
        process_model(os.path.abspath(args.model_dir))
    else:
        ap.error("provide a model_dir or --all")


if __name__ == "__main__":
    main()
