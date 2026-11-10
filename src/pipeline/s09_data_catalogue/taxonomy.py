"""Loader + validator for the versioned term taxonomy.

The taxonomy is a separate, versioned artifact (`taxonomy/term_taxonomy_v1.yaml`)
that defines the allowed categories and subcategories. Extraction never invents
categories; classification assigns terms to this vocabulary.

Validation rules (run by `--validate`, and on every load in strict mode):
  * category_id is unique
  * parent_category_id, when set, exists
  * hierarchy_level UPPER has no parent; SUB has a parent of level UPPER
  * allowed_parent_ids (when given) equals the declared parent set
  * no cycles in the parent chain
  * every category carries the full required field set
  * exactly one primary category per term, enforced downstream
  * UNCERTAIN, if present, is reserved: UPPER level, no parent, excluded from stats

Usage:
    PYTHONPATH=src python src/scripts/vllm_termpop/taxonomy.py --validate
    PYTHONPATH=src python src/scripts/vllm_termpop/taxonomy.py --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "data" / "reference" / "taxonomy" / "term_taxonomy_v1.yaml"

REQUIRED_FIELDS = [
    "category_id", "category_label", "category_definition", "parent_category_id",
    "hierarchy_level", "inclusion_criteria", "exclusion_criteria",
    "positive_examples", "negative_examples", "allowed_parent_ids",
    "ontology_source", "ontology_version", "mapping_status", "review_status",
    "notes",
]
RESERVED = {"UNCERTAIN"}


class Taxonomy:
    def __init__(self, path=DEFAULT_PATH):
        if yaml is None:
            raise RuntimeError("PyYAML is required to read the taxonomy YAML")
        path = Path(path)
        self.path = path
        self.raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.version = str(self.raw.get("version", ""))
        self.taxonomy_id = self.raw.get("taxonomy_id", "")
        self.categories = {c["category_id"]: c for c in self.raw["categories"]}

    # ── queries ──
    def upper(self):
        return [c for c in self.categories.values()
                if c["hierarchy_level"] == "UPPER" and c["category_id"] not in RESERVED]

    def subcategories(self, upper_id=None):
        subs = [c for c in self.categories.values() if c["hierarchy_level"] == "SUB"]
        return [c for c in subs if upper_id is None or c["parent_category_id"] == upper_id]

    def children(self, category_id):
        return [c["category_id"] for c in self.categories.values()
                if c.get("parent_category_id") == category_id]

    def valid_pair(self, upper_id, sub_id):
        """True if sub_id is a legal subcategory of upper_id."""
        if sub_id is None:
            return upper_id in self.categories
        sub = self.categories.get(sub_id)
        return bool(sub) and sub.get("parent_category_id") == upper_id

    def prompt_vocabulary(self):
        """Compact vocabulary block for a classifier prompt."""
        lines = []
        for up in sorted(self.upper(), key=lambda c: c["category_id"]):
            subs = [c["category_id"] for c in
                    sorted(self.subcategories(up["category_id"]),
                           key=lambda c: c["category_id"])]
            lines.append("%s: %s | subcategories: %s"
                         % (up["category_id"], up["category_definition"].strip().replace("\n", " "),
                            ", ".join(subs) if subs else "(none)"))
        return "\n".join(lines)

    # ── validation ──
    def validate(self):
        errors, warnings = [], []
        cats = self.categories

        if len(self.raw.get("categories", [])) != len(cats):
            errors.append("duplicate category_id values in taxonomy")

        for cid, c in cats.items():
            missing = [f for f in REQUIRED_FIELDS if f not in c]
            if missing:
                errors.append("%s: missing fields %s" % (cid, missing))
            level = c.get("hierarchy_level")
            parent = c.get("parent_category_id")
            if level not in ("UPPER", "SUB", "ROOT"):
                errors.append("%s: bad hierarchy_level %r" % (cid, level))
            if level == "UPPER" and parent:
                errors.append("%s: UPPER category must not have a parent" % cid)
            if level == "SUB":
                if not parent:
                    errors.append("%s: SUB category needs a parent" % cid)
                elif parent not in cats:
                    errors.append("%s: parent %r does not exist" % (cid, parent))
                elif cats[parent]["hierarchy_level"] != "UPPER":
                    errors.append("%s: parent %r is not UPPER" % (cid, parent))
            allowed = c.get("allowed_parent_ids") or []
            if allowed and parent and allowed != [parent]:
                errors.append("%s: allowed_parent_ids %s != parent %r"
                              % (cid, allowed, parent))
            if c.get("mapping_status") not in ("EXACT", "BROADER", "NARROWER",
                                              "CUSTOM", "UNRESOLVED"):
                warnings.append("%s: unusual mapping_status %r"
                                % (cid, c.get("mapping_status")))
            if c.get("review_status") not in ("DRAFT", "APPROVED", "DEPRECATED"):
                warnings.append("%s: unusual review_status %r"
                                % (cid, c.get("review_status")))

        # cycles
        for cid in cats:
            seen, cur = set(), cid
            while cur:
                if cur in seen:
                    errors.append("cycle detected at %s" % cid)
                    break
                seen.add(cur)
                cur = cats.get(cur, {}).get("parent_category_id")

        for cid in RESERVED & set(cats):
            c = cats[cid]
            if c["hierarchy_level"] != "UPPER" or c.get("parent_category_id"):
                errors.append("%s: reserved category must be UPPER with no parent" % cid)

        for cid, c in cats.items():
            if c.get("hierarchy_level") == "UPPER" and cid not in RESERVED:
                if not self.subcategories(cid):
                    warnings.append("%s: UPPER category has no subcategories" % cid)

        return errors, warnings

    def summary(self):
        ups = self.upper()
        return {
            "taxonomy_id": self.taxonomy_id,
            "version": self.version,
            "upper_categories": len(ups),
            "subcategories": len(self.subcategories()),
            "reserved": sorted(RESERVED & set(self.categories)),
            "total_entries": len(self.categories),
        }

    def to_rows(self):
        rows = []
        for c in self.raw["categories"]:
            row = {}
            for f in REQUIRED_FIELDS:
                v = c.get(f)
                if isinstance(v, list):
                    v = " | ".join(str(x) for x in v)
                row[f] = "" if v is None else v
            rows.append(row)
        return rows


def main():
    ap = argparse.ArgumentParser(description="Validate / export the term taxonomy")
    ap.add_argument("--taxonomy", default=str(DEFAULT_PATH))
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--csv", help="write the taxonomy as a flat CSV")
    ap.add_argument("--prompt", action="store_true",
                    help="print the compact classifier vocabulary block")
    ap.add_argument("--json", action="store_true", help="print a summary as JSON")
    args = ap.parse_args()

    tax = Taxonomy(args.taxonomy)
    if args.validate or not (args.csv or args.prompt or args.json):
        errors, warnings = tax.validate()
        print(json.dumps(tax.summary(), indent=2))
        for w in warnings:
            print("WARN:", w)
        for e in errors:
            print("ERROR:", e)
        print("VALID" if not errors else "INVALID (%d errors)" % len(errors))
        if errors:
            sys.exit(1)
    if args.prompt:
        print(tax.prompt_vocabulary())
    if args.json:
        print(json.dumps(tax.summary(), indent=2))
    if args.csv:
        rows = tax.to_rows()
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=REQUIRED_FIELDS)
            w.writeheader()
            w.writerows(rows)
        print("wrote", args.csv)


if __name__ == "__main__":
    main()
