#!/usr/bin/env python3
"""Resolve resume.yaml into one tailored view, as JSON.

    python tools/resolve.py --profile full --output web [-o dist/resolved.json]

Pipeline: load -> merge private.yaml -> validate -> cross-check -> flatten
profile -> select -> order -> emit. Templates (web, PDF) read only the JSON.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ("education", "skills", "certifications", "projects", "experience")
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
SELECTION_FIELDS = ("tags", "outputs", "draft")

# Nested selectable lists, named explicitly (never walk lists generically).
NESTED = {
    "education": ("honors", "highlights"),
    "projects": ("highlights",),
    "experience": ("highlights",),
    "skills": ("items",),
    "certifications": (),
}


class ResolveError(Exception):
    """Collects every problem found, so one run reports them all."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


# --------------------------------------------------------------------------
# 1. Load
# --------------------------------------------------------------------------
def load_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ResolveError([f"{path}: file not found"])
    except yaml.YAMLError as e:
        raise ResolveError([f"{path}: invalid YAML: {e}"])
    if not isinstance(data, dict):
        raise ResolveError([f"{path}: top level must be a mapping"])
    return data


# --------------------------------------------------------------------------
# 2. Merge private.yaml
# --------------------------------------------------------------------------
def merge(base, over):
    """Dicts merge recursively; lists of id'd dicts merge by id
    (match = recursive merge, new id = append); anything else is replaced."""
    if isinstance(base, dict) and isinstance(over, dict):
        return {k: merge(base[k], v) if k in base else v
                for k, v in {**base, **over}.items()}
    if (isinstance(base, list) and isinstance(over, list)
            and all(isinstance(x, dict) and "id" in x for x in base + over)):
        out = {x["id"]: x for x in base}
        for x in over:
            out[x["id"]] = merge(out[x["id"]], x) if x["id"] in out else x
        return list(out.values())
    return over


# --------------------------------------------------------------------------
# 3. Validate
# --------------------------------------------------------------------------
def validate(data: dict, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data),
                    key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        raise ResolveError([
            f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in errors
        ])


# --------------------------------------------------------------------------
# 4. Cross-checks
# --------------------------------------------------------------------------
def collect_ids(data: dict) -> dict[str, str]:
    ids: dict[str, str] = {}
    problems: list[str] = []

    def add(item, where):
        if isinstance(item, dict) and "id" in item:
            iid = item["id"]
            if iid in ids:
                problems.append(f"duplicate id '{iid}' at {where} and {ids[iid]}")
            else:
                ids[iid] = where

    for c in data.get("basics", {}).get("contact", []):
        add(c, "basics/contact")
    for section in SECTIONS:
        for entry in data.get(section, []) or []:
            add(entry, section)
            eid = entry.get("id", "?")
            for key in NESTED[section]:
                for child in entry.get(key, []) or []:
                    add(child, f"{section}/{eid}/{key}")
    if problems:
        raise ResolveError(problems)
    return ids


def check_profiles(profiles: dict, ids: dict[str, str]) -> None:
    problems: list[str] = []
    for name, p in profiles.items():
        for key in ("include", "exclude", "order"):
            for iid in p.get(key, []):
                if iid not in ids:
                    problems.append(f"profile '{name}': {key} names unknown id '{iid}'")
        both = set(p.get("include", [])) & set(p.get("exclude", []))
        for iid in sorted(both):
            problems.append(f"profile '{name}': '{iid}' is in both include and exclude")
        # extends chain
        seen, cur = [name], p
        while "extends" in cur:
            parent = cur["extends"]
            if parent not in profiles:
                problems.append(f"profile '{seen[-1]}': extends unknown profile '{parent}'")
                break
            if parent in seen:
                problems.append(f"profile '{name}': extends cycle {' -> '.join(seen + [parent])}")
                break
            seen.append(parent)
            cur = profiles[parent]
    if problems:
        raise ResolveError(problems)


# --------------------------------------------------------------------------
# 5. Flatten a profile
# --------------------------------------------------------------------------
@dataclass
class Profile:
    name: str
    tags: str | set[str] = "*"
    sections: list[str] = field(default_factory=lambda: list(SECTIONS))
    include: set[str] = field(default_factory=set)
    exclude: set[str] = field(default_factory=set)
    order: list[str] = field(default_factory=list)


def flatten_profile(profiles: dict, name: str) -> Profile:
    if name not in profiles:
        known = ", ".join(sorted(profiles)) or "(none)"
        raise ResolveError([f"unknown profile '{name}' (known: {known})"])
    chain, cur = [], name
    while cur is not None:                 # child -> base; cycles already rejected
        chain.append(profiles[cur])
        cur = profiles[cur].get("extends")
    p = Profile(name=name)
    for layer in reversed(chain):          # base -> child
        if "tags" in layer:
            p.tags = "*" if layer["tags"] == "*" else set(layer["tags"])
        if "sections" in layer:
            p.sections = list(layer["sections"])
        if "order" in layer:
            p.order = list(layer["order"])
        inc, exc = set(layer.get("include", [])), set(layer.get("exclude", []))
        p.include = (p.include - exc) | inc
        p.exclude = (p.exclude - inc) | exc
    return p


# --------------------------------------------------------------------------
# 6. Selection
# --------------------------------------------------------------------------
def keep(item, p: Profile, output: str) -> bool:
    if not isinstance(item, dict):       # plain-string skills: always kept
        return True
    if item.get("draft"):
        return False
    if "outputs" in item and output not in item["outputs"]:
        return False
    iid = item.get("id")
    if iid in p.include:
        return True                      # beats tags, not draft/outputs
    if iid in p.exclude:
        return False
    tags = item.get("tags", [])
    return p.tags == "*" or not tags or bool(set(tags) & p.tags)


def select_section(name: str, entries: list, p: Profile, output: str,
                   warn) -> list:
    result = []
    for entry in entries or []:
        eid = entry.get("id", "?")
        if not keep(entry, p, output):
            for key in NESTED[name]:
                for child in entry.get(key, []) or []:
                    if isinstance(child, dict) and child.get("id") in p.include:
                        warn(f"'{child['id']}' is included but its parent "
                             f"'{eid}' was filtered out")
            continue
        entry = dict(entry)
        for key in NESTED[name]:
            if key in entry:
                entry[key] = [c for c in entry[key] if keep(c, p, output)]
        if name == "skills" and not entry.get("items"):
            continue
        if name in ("projects", "experience") and not entry.get("highlights"):
            warn(f"'{eid}' has no bullets left in profile '{p.name}'")
        result.append(entry)
    return result


# --------------------------------------------------------------------------
# 7. Ordering
# --------------------------------------------------------------------------
def start_key(entry: dict) -> str:
    if "terms" in entry:
        return max(t["start"] for t in entry["terms"])
    return entry.get("start") or entry.get("date") or ""


def order_entries(entries: list, order: list[str]) -> list:
    rank = {iid: i for i, iid in enumerate(order)}
    pinned = sorted((e for e in entries if e.get("id") in rank),
                    key=lambda e: rank[e["id"]])
    rest = sorted((e for e in entries if e.get("id") not in rank),
                  key=start_key, reverse=True)
    return pinned + rest


# --------------------------------------------------------------------------
# Display strings (computed once so web and PDF agree)
# --------------------------------------------------------------------------
def fmt_date(d: str) -> str:
    if d == "present":
        return "Present"
    parts = d.split("-")
    if len(parts) >= 2:
        return f"{MONTHS[int(parts[1]) - 1]} {parts[0]}"
    return parts[0]


def fmt_range(start: str, end: str | None) -> str:
    if not end:
        return fmt_date(start)
    if end != "present" and start[:4] == end[:4]:
        return f"{MONTHS[int(start[5:7]) - 1]}–{fmt_date(end)}"
    return f"{fmt_date(start)} – {fmt_date(end)}"


def add_display(section: str, entry: dict) -> dict:
    if "terms" in entry:
        terms = sorted(entry["terms"], key=lambda t: t["start"], reverse=True)
        entry["dates"] = " · ".join(fmt_range(t["start"], t.get("end")) for t in terms)
    elif "start" in entry:
        entry["dates"] = fmt_range(entry["start"], entry.get("end"))
    if section == "certifications" and "date" in entry:
        entry["date_display"] = fmt_date(entry["date"])
        if "expires" in entry:
            entry["expires_display"] = fmt_date(entry["expires"])
    return entry


def strip_selection_fields(obj):
    if isinstance(obj, dict):
        return {k: strip_selection_fields(v) for k, v in obj.items()
                if k not in SELECTION_FIELDS}
    if isinstance(obj, list):
        return [strip_selection_fields(x) for x in obj]
    return obj


# --------------------------------------------------------------------------
# 8. Assemble
# --------------------------------------------------------------------------
def last_updated(source: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", source.name],
            cwd=source.parent, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out or date.today().isoformat()
    except (OSError, subprocess.CalledProcessError):
        return date.today().isoformat()


def resolve(source: Path, private: Path | None, schema: Path,
            profile_name: str, output: str, warn=print) -> dict:
    data = load_yaml(source)
    if private is not None:
        data = merge(data, load_yaml(private))
    validate(data, schema)
    ids = collect_ids(data)
    profiles = data.get("profiles", {}) or {}
    check_profiles(profiles, ids)
    p = flatten_profile(profiles, profile_name)

    basics = dict(data["basics"])
    basics["contact"] = [c for c in basics.get("contact", []) if keep(c, p, output)]

    sections = {}
    for name in p.sections:
        entries = select_section(name, data.get(name, []), p, output, warn)
        entries = order_entries(entries, p.order)
        sections[name] = [add_display(name, e) for e in entries]

    updated = last_updated(source)
    return strip_selection_fields({
        "meta": {
            "profile": p.name,
            "output": output,
            "updated": updated,
            "updated_display": fmt_date(updated),
        },
        "basics": basics,
        "sections": sections,
    })


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=ROOT / "resume.yaml")
    ap.add_argument("--private", type=Path, default=ROOT / "private.yaml")
    ap.add_argument("--schema", type=Path, default=ROOT / "resume.schema.json")
    ap.add_argument("--profile", default="full")
    ap.add_argument("--output", choices=("web", "pdf"), required=True)
    ap.add_argument("-o", "--out", type=Path, help="default: stdout")
    args = ap.parse_args(argv)

    warn = lambda msg: print(f"warning: {msg}", file=sys.stderr)
    try:
        result = resolve(args.source,
                         args.private if args.private.exists() else None,
                         args.schema, args.profile, args.output, warn)
    except ResolveError as e:
        for prob in e.problems:
            print(f"error: {prob}", file=sys.stderr)
        return 1

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())