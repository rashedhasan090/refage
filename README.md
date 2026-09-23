# refage

Offline stdlib Python CLI that flags **recency language** ("recent", "SOTA", "latest", …) when nearby citations have **stale bibliographic years**.

Unlike **claimcite** (claim↔citation coverage) and **hedgescope** (hedging tone), **refage** checks whether "recent/SOTA" wording is backed by actually recent bibliographic years.

## Install

```bash
pip install -e .
# or
pip install -e ".[dev]"
```

## Usage

```bash
refage draft.md --bib refs.bib
refage paper.tex notes.md --bib refs.bib --max-age 3
refage draft.md --bib refs.bib --json
refage draft.md --bib refs.bib --fail-on never
```

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--bib` | required | BibTeX file |
| `--max-age` | `5` | Years before current calendar year; older = stale |
| `--json` | off | Machine-readable output |
| `--fail-on` | `findings` | `findings` \| `never` \| `errors` |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Clean (or `--fail-on never`) |
| 1 | Findings (when `--fail-on findings`) |
| 2 | Usage / IO error |

### What it detects

- Recency phrases (word-boundary): `recent`, `recently`, `state-of-the-art`, `state of the art`, `SOTA`, `latest`, `cutting-edge`, `newly`
- Nearby citations (~2 sentences / ~400 chars): Markdown `[@key]`, `[@a;@b]`; LaTeX `\cite{}`, `\citep{}`, `\citet{}`, …
- Finding kinds:
  - **stale** — nearby cite year older than cutoff
  - **no_year** — nearby cite missing year (or absent from bib)
  - **no_citation** — recency phrase with no nearby cite

Runtime depends on the Python standard library only.

## Demo

```bash
# Stale + gaps (expect exit 1)
refage examples/draft.md --bib examples/refs.bib

# Clean (expect exit 0)
refage examples/draft_clean.md --bib examples/refs.bib
```

## License

MIT © 2026 Rashed Hasan
