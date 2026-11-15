# resume

One YAML file builds the web résumé at **[eravas.ca/resume](https://eravas.ca/resume)** and the PDF at **[eravas.ca/resume.pdf](https://eravas.ca/resume.pdf)**. Every push to `main` rebuilds and redeploys both.

```
resume.yaml ──► tools/resolve.py ──► resolved JSON ──┬─► templates/web.html.j2 ──► dist/resume/index.html
(+ private.yaml)   validate, pick a                  │
                   profile, order, format            └─► templates/resume.typ ───► dist/resume.pdf
```

The resolver is the only place content decisions are made. Both templates just lay out what it hands them, so the page and the PDF can't disagree about what's in the résumé.

## Editing

All resume content lives in [`resume.yaml`](resume.yaml), checked against [`resume.schema.json`](resume.schema.json). Editors with the YAML language server (VS Code, Neovim, Zed) pick the schema up automatically from the file's first line.

- **Dates** are quoted `"YYYY-MM"`. Unquoted, some YAML parsers turn them into date objects.
- **`draft: true`** hides an entry everywhere until it's ready.
- **`outputs: [pdf]`** or **`[web]`** limits an item to one output.
- **Inline formatting** in bullets: `**bold**`, `*italic*`, `[label](https://…)`.

If the YAML is invalid, the build fails and nothing deploys; the live site stays as it was.

## Tailoring

Every entry, bullet and skill can carry `tags`. A **profile** (at the bottom of `resume.yaml`) is a view over the content:

- untagged items appear in every profile
- tagged items appear only in profiles that ask for one of their tags
- `include` / `exclude` force individual ids in or out
- `order` pins entries to the top; everything else is newest first
- `extends` builds one profile on another

The web page uses `full`; the hosted PDF uses `public`.

## Private data

`private.yaml` is gitignored and merged over `resume.yaml` when present (lists merge by `id`). It holds the phone number, the profile rule that keeps it out of the public PDF, and any profiles named after specific applications. See [`private.example.yaml`](private.example.yaml). The build refuses to write a public PDF that contains a phone number.

## Building locally

Needs Python 3.12+, [Typst](https://github.com/typst/typst) 0.14+, and Trebuchet MS (Microsoft core fonts: `ttf-ms-fonts` on Arch, `ttf-mscorefonts-installer` on Ubuntu).

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python tools/build.py --pdf public                # web page + public PDF, as deployed
python -m http.server -d dist 8000                # preview at localhost:8000/resume/
python tools/build.py --pdf embedded --no-web     # tailored PDF -> out/resume-embedded.pdf
```

Tailored PDFs go to `out/` (gitignored) and include private data; only the `public` profile is ever written to `dist/`.

## Deployment

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) builds on every push to `main` and deploys `dist/` to a Cloudflare Worker serving `eravas.ca/resume*` ([`wrangler.jsonc`](wrangler.jsonc)). It needs `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in the specified environment, in this case `prod`.

## Layout

```
resume.yaml            content
resume.schema.json     schema for resume.yaml
tools/resolve.py       load, merge, validate, select, order -> JSON
tools/build.py         renders the web page and PDF
templates/             web.html.j2, resume.typ
static/assets/         logo and favicons, copied next to the page
```

## Fonts

Web: Germania One, Newsreader and IBM Plex Mono (Google Fonts, SIL OFL). PDF: Trebuchet MS, installed on the build machine and never committed.
