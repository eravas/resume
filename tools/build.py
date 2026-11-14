#!/usr/bin/env python3
"""Build the web résumé.

    python tools/build.py --profile full [--pdf-url /resume.pdf] [--out-dir dist]

Writes <out-dir>/resume/index.html and copies static/ next to it.
Omit --pdf-url until the PDF is actually deployed: the page then hides
its PDF links instead of pointing at a 404.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve import ROOT, ResolveError, resolve  # noqa: E402

# Web layout: which bands exist and what their big words say.
BANDS = (
    ("projects", "Projects", ("projects",)),
    ("experience", "Experience", ("experience",)),
    ("education", "Education", ("education",)),
    ("skills", "Skills", ("skills", "certifications")),
)

# Skill groups that share one column on the web page, in display order.
# Groups not listed here get their own column after these, in YAML order.
SKILL_COLUMNS = (
    ("languages", "tools"),
    ("robotics-embedded",),
)

_LINK = re.compile(r"\[([^\]]+)\]\(((?:https?://|mailto:)[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")


def inline(text: str) -> Markup:
    """Escape, then allow **bold**, *italic* and [label](https://…)."""
    s = str(escape(text))
    s = _LINK.sub(r'<a href="\2">\1</a>', s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    s = _ITAL.sub(r"<em>\1</em>", s)
    return Markup(s)


def contact_href(c: dict) -> str:
    if c.get("url"):
        return c["url"]
    kind, value = c.get("kind"), c.get("value", "")
    if kind == "email":
        return f"mailto:{value}"
    if kind == "phone":
        return "tel:" + re.sub(r"[^\d+]", "", value)
    return value


def skill_columns(groups: list[dict]) -> list[list[dict]]:
    by_id = {g.get("id"): g for g in groups}
    used, cols = set(), []
    for ids in SKILL_COLUMNS:
        col = [by_id[i] for i in ids if i in by_id]
        if col:
            cols.append(col)
            used.update(ids)
    cols += [[g] for g in groups if g.get("id") not in used]
    return cols


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default="full")
    ap.add_argument("--pdf-url", default=None)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    args = ap.parse_args(argv)

    warn = lambda msg: print(f"warning: {msg}", file=sys.stderr)
    private = ROOT / "private.yaml"
    try:
        data = resolve(ROOT / "resume.yaml", private if private.exists() else None,
                       ROOT / "resume.schema.json", args.profile, "web", warn)
    except ResolveError as e:
        for prob in e.problems:
            print(f"error: {prob}", file=sys.stderr)
        return 1

    sections = data["sections"]
    bands = [{"id": "intro", "word": "Résumé"}] + [
        {"id": bid, "word": word}
        for bid, word, keys in BANDS
        if any(sections.get(k) for k in keys)
    ]

    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["inline"] = inline
    env.filters["contact_href"] = contact_href

    html = env.get_template("web.html.j2").render(
        basics=data["basics"],
        sections=sections,
        meta=data["meta"],
        bands=bands,
        skill_columns=skill_columns(sections.get("skills") or []),
        pdf_url=args.pdf_url,
    )

    out = args.out_dir / "resume"
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    static = ROOT / "static"
    if static.is_dir():
        shutil.copytree(static, out, dirs_exist_ok=True)
    print(f"wrote {out / 'index.html'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())