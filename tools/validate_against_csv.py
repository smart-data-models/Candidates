#!/usr/bin/env python3
"""
Validate a Candidates schema.json against a real-world CSV dataset.

Generic by design: point it at any schema.json, a CSV file, and a mapping
from CSV column name -> JSON Schema property name, and it will convert each
sampled row to JSON per the mapping and validate it against the schema,
reporting a pass/fail breakdown by column.

Usage:
    python3 tools/validate_against_csv.py \
        --schema standards/madrid-accidentes-trafico/models/AccidentInvolvedPerson/schema.json \
        --csv /path/to/data.csv \
        --mapping standards/madrid-accidentes-trafico/models/AccidentInvolvedPerson/csv-mapping.json \
        --delimiter ";" \
        --sample 2000 --seed 42 --stratify

The mapping file is a JSON object: {"csv_column_name": "jsonPropertyName", ...}.
Values that are the literal string "NULL" (or the mapping's --null-token) are
passed through unchanged by default -- pass --normalize-null to instead omit
the property from the JSON when the CSV value equals the null token.

Numeric properties (per the schema's own "type": "number"/"integer") are cast
automatically; everything else is passed through as a string, since that
matches what a real CSV row actually is.
"""
import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict

from jsonschema import Draft202012Validator, FormatChecker


def load_rows(csv_path, delimiter):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        return list(reader), reader.fieldnames


def stratify_columns_from_schema(mapping, schema):
    """Only stratify on columns whose mapped property is an enum in the schema --
    stratifying on a high-cardinality identifier column (e.g. a case number) would
    select nearly the whole dataset, defeating the point of sampling."""
    props = schema["properties"]
    return [c for c, p in mapping.items() if "enum" in props.get(p, {})]


def stratified_sample(rows, mapping, schema, sample_size, seed):
    """Guarantee at least one row per distinct value of every enum-mapped column,
    then fill up to sample_size with a random selection (deterministic seed)."""
    rng = random.Random(seed)
    strat_cols = stratify_columns_from_schema(mapping, schema)
    seen_value = defaultdict(set)  # column -> set of values already covered
    chosen_indices = []
    chosen_set = set()

    # Pass 1: cover every distinct value of every enum column at least once.
    for i, row in enumerate(rows):
        newly_covered = False
        for col in strat_cols:
            val = row.get(col, "")
            if val not in seen_value[col]:
                newly_covered = True
        if newly_covered:
            for col in strat_cols:
                seen_value[col].add(row.get(col, ""))
            chosen_indices.append(i)
            chosen_set.add(i)

    # Pass 2: fill randomly up to sample_size.
    remaining = [i for i in range(len(rows)) if i not in chosen_set]
    rng.shuffle(remaining)
    while len(chosen_indices) < sample_size and remaining:
        chosen_indices.append(remaining.pop())

    print(f"Stratifying on columns (enum-valued in schema): {strat_cols}")
    return [rows[i] for i in sorted(chosen_indices[:max(sample_size, len(chosen_set))])]


def coerce(value, prop_schema):
    jtype = prop_schema.get("type")
    if jtype == "number":
        try:
            return float(value.replace(",", "."))
        except (ValueError, AttributeError):
            return value
    if jtype == "integer":
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    return value


def to_iso_date(value):
    """Best-effort dd/mm/yyyy -> yyyy-mm-dd; returns the input unchanged if it doesn't match."""
    parts = value.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        d, m, y = parts
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return value


def row_to_entity(row, mapping, schema, null_token, normalize_null, entity_type, id_field, date_columns):
    props = schema["properties"]
    entity = {"id": f"urn:ngsi-ld:{entity_type}:{row.get(id_field, 'unknown')}", "type": entity_type}
    for csv_col, prop_name in mapping.items():
        raw = row.get(csv_col, "")
        if raw is None or raw.strip() == "":
            continue
        if normalize_null and raw == null_token:
            continue
        if csv_col in date_columns:
            raw = to_iso_date(raw)
        prop_schema = props.get(prop_name, {})
        entity[prop_name] = coerce(raw, prop_schema)
    return entity


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--mapping", required=True, help="JSON file: {csv_column: jsonProperty}")
    ap.add_argument("--delimiter", default=";")
    ap.add_argument("--sample", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stratify", action="store_true",
                     help="Guarantee every distinct value of every mapped column appears at least once")
    ap.add_argument("--null-token", default="NULL")
    ap.add_argument("--normalize-null", action="store_true",
                     help="Omit the property instead of keeping the literal null-token string")
    ap.add_argument("--id-field", default=None, help="CSV column to use as the entity id suffix")
    ap.add_argument("--show-errors", type=int, default=10, help="Max distinct error messages to print per column")
    ap.add_argument("--no-format-check", action="store_true",
                     help="Skip format assertion (date/time/uri/...) -- structural checks only")
    ap.add_argument("--date-columns", default="", help="Comma-separated CSV columns to parse from dd/mm/yyyy to ISO 8601 before validating")
    args = ap.parse_args()

    schema = json.load(open(args.schema))
    mapping = json.load(open(args.mapping))
    entity_type = schema["properties"]["type"]["enum"][0]
    id_field = args.id_field or next(iter(mapping))

    rows, fieldnames = load_rows(args.csv, args.delimiter)
    print(f"Loaded {len(rows)} rows from {args.csv} (columns: {len(fieldnames)})")

    missing_cols = [c for c in mapping if c not in fieldnames]
    if missing_cols:
        sys.exit(f"ERROR: mapping references columns not in the CSV: {missing_cols}")

    if args.stratify:
        sample = stratified_sample(rows, mapping, schema, args.sample, args.seed)
    else:
        rng = random.Random(args.seed)
        sample = rng.sample(rows, min(args.sample, len(rows)))

    print(f"Validating a sample of {len(sample)} rows "
          f"({'stratified: every distinct value covered + random fill' if args.stratify else 'random'})\n")

    format_checker = None if args.no_format_check else FormatChecker()
    validator = Draft202012Validator(schema, format_checker=format_checker)
    date_columns = set(c for c in args.date_columns.split(",") if c)
    n_pass = n_fail = 0
    errors_by_prop = Counter()
    example_errors = defaultdict(list)

    for row in sample:
        entity = row_to_entity(row, mapping, schema, args.null_token, args.normalize_null, entity_type, id_field, date_columns)
        errs = sorted(validator.iter_errors(entity), key=str)
        if not errs:
            n_pass += 1
            continue
        n_fail += 1
        for e in errs:
            prop = ".".join(str(p) for p in e.path) or "(root)"
            errors_by_prop[prop] += 1
            if len(example_errors[prop]) < args.show_errors:
                example_errors[prop].append((e.message, row.get(id_field)))

    total = n_pass + n_fail
    print(f"=== RESULT: {n_pass}/{total} rows valid ({n_pass/total*100:.1f}%) ===\n")

    if errors_by_prop:
        print("Failures by property:")
        for prop, count in errors_by_prop.most_common():
            print(f"\n  {prop}: {count} row(s) failed")
            for msg, row_id in example_errors[prop]:
                print(f"      [{row_id}] {msg[:140]}")
    else:
        print("No validation errors in the sample.")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
