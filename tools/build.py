#!/usr/bin/env python3
"""Build the web résumé and, optionally, the PDF.

    python tools/build.py                          # web only (profile: full)
    python tools/build.py --pdf public             # web + dist/resume.pdf
    python tools/build.py --pdf embedded --no-web  # tailored PDF -> out/

Web: <out-dir>/resume/index.html, with static/ copied next to it.
PDF: the "public" profile goes to <out-dir>/resume.pdf (deployed) and must
not contain a phone number; any other profile goes to out/resume-<profile>.pdf
(gitignored, for applications, private.yaml merged in when present).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import json  # noqa: E402
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


def build_pdf(profile: str, out_dir: Path, warn) -> Path:
    private = ROOT / "private.yaml"
    data = resolve(ROOT / "resume.yaml", private if private.exists() else None,
                   ROOT / "resume.schema.json", profile, "pdf", warn)

    public = profile == "public"
    if public and any(c.get("kind") == "phone" for c in data["basics"]["contact"]):
        raise ResolveError(["the public PDF would contain a phone number; "
                            "exclude it in the 'public' profile"])

    scratch = ROOT / "build"
    scratch.mkdir(exist_ok=True)
    data_file = scratch / f"resolved-{profile}.json"
    data_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    out = out_dir / "resume.pdf" if public else ROOT / "out" / f"resume-{profile}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)

    typst = shutil.which("typst")
    if typst is None:
        raise ResolveError(["typst not found on PATH (https://github.com/typst/typst#installation)"])
    cmd = [typst, "compile", "--root", str(ROOT),
           "--input", f"data=/{data_file.relative_to(ROOT).as_posix()}"]
    fonts = ROOT / "fonts"
    if fonts.is_dir():
        cmd += ["--font-path", str(fonts)]
    cmd += [str(ROOT / "templates" / "resume.typ"), str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise ResolveError([f"typst failed (exit {result.returncode})"])
    print(f"wrote {out}", file=sys.stderr)
    return out


def build_web(profile: str, out_dir: Path, pdf_url: str | None, warn) -> None:
    private = ROOT / "private.yaml"
    data = resolve(ROOT / "resume.yaml", private if private.exists() else None,
                   ROOT / "resume.schema.json", profile, "web", warn)

    sections = data["sections"]
    bands = [{"id": "intro", "word": "Résumé"}] + [
        {"id": bid, "word": word}
        for bid, word, keys in BANDS
        if any(sections.get(k) for k in keys)
    ]

    env = Environment(
        loader=FileSystemLoader([ROOT / "templates", ROOT / "static"]),
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
        pdf_url=pdf_url,
    )

    out = out_dir / "resume"
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    static = ROOT / "static"
    if static.is_dir():
        shutil.copytree(static, out, dirs_exist_ok=True)
    print(f"wrote {out / 'index.html'}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default="full", help="web profile (default: full)")
    ap.add_argument("--pdf", metavar="PROFILE", help="also build a PDF for this profile")
    ap.add_argument("--no-web", action="store_true", help="skip the web page")
    ap.add_argument("--pdf-url", default=None,
                    help="link target for the PDF on the web page "
                         "(default: /resume.pdf when --pdf public is built)")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    args = ap.parse_args(argv)

    warn = lambda msg: print(f"warning: {msg}", file=sys.stderr)
    try:
        pdf_url = args.pdf_url
        if args.pdf:
            build_pdf(args.pdf, args.out_dir, warn)
            if args.pdf == "public" and pdf_url is None:
                pdf_url = "/resume.pdf"
        if not args.no_web:
            build_web(args.profile, args.out_dir, pdf_url, warn)
    except ResolveError as e:
        for prob in e.problems:
            print(f"error: {prob}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())