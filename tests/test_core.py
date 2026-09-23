"""Tests for refage core."""

from __future__ import annotations

from pathlib import Path

import pytest

from refage.core import (
    analyze_text,
    find_citations,
    find_recency_phrases,
    parse_bibtex,
    scan,
)
from refage.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_parse_bibtex_years():
    bib = (EXAMPLES / "refs.bib").read_text(encoding="utf-8")
    years = parse_bibtex(bib)
    assert years["smith2015"] == 2015
    assert years["jones2018"] == 2018
    assert years["lee2024"] == 2024
    assert years["chen2023"] == 2023
    assert years["noyearkey"] is None


def test_find_recency_phrases():
    text = "A recent and state-of-the-art SOTA method was newly released."
    phrases = find_recency_phrases(text)
    labels = {p.phrase for p in phrases}
    assert "recent" in labels
    assert "state-of-the-art" in labels
    assert "SOTA" in labels
    assert "newly" in labels
    # "state of the art" phrase variant
    text2 = "This is the state of the art approach."
    p2 = find_recency_phrases(text2)
    assert any(p.phrase == "state of the art" for p in p2)


def test_find_citations_md_and_latex():
    text = "See [@a;@b] and \\citep{c,d} plus \\citet{e}."
    cites = find_citations(text)
    keys = sorted({k for c in cites for k in c.keys})
    assert keys == ["a", "b", "c", "d", "e"]


def test_stale_finding():
    text = "Recent work [@smith2015] is outdated."
    bib = {"smith2015": 2015}
    findings = analyze_text(text, "t.md", bib, current_year=2026, max_age=5)
    kinds = {f.kind for f in findings}
    assert "stale" in kinds
    stale = [f for f in findings if f.kind == "stale"][0]
    assert "smith2015" in stale.citation_keys


def test_clean_recent_citation():
    text = "The latest results [@lee2024] are fine."
    bib = {"lee2024": 2024}
    findings = analyze_text(text, "t.md", bib, current_year=2026, max_age=5)
    assert findings == []


def test_no_citation():
    text = "Cutting-edge systems dominate this field without refs here."
    findings = analyze_text(text, "t.md", {}, current_year=2026, max_age=5)
    assert any(f.kind == "no_citation" for f in findings)


def test_no_year():
    text = "Recently [@noyearkey] claimed X."
    bib = {"noyearkey": None}
    findings = analyze_text(text, "t.md", bib, current_year=2026, max_age=5)
    assert any(f.kind == "no_year" for f in findings)


def test_scan_examples():
    result = scan(
        [EXAMPLES / "draft.md"],
        EXAMPLES / "refs.bib",
        max_age=5,
        current_year=2026,
    )
    kinds = {f.kind for f in result.findings}
    assert "stale" in kinds
    assert "no_citation" in kinds
    assert "no_year" in kinds


def test_scan_clean_example():
    result = scan(
        [EXAMPLES / "draft_clean.md"],
        EXAMPLES / "refs.bib",
        max_age=5,
        current_year=2026,
    )
    assert result.findings == []


def test_cli_findings_exit(capsys):
    code = main(
        [
            str(EXAMPLES / "draft.md"),
            "--bib",
            str(EXAMPLES / "refs.bib"),
            "--year",
            "2026",
            "--fail-on",
            "findings",
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "stale" in out


def test_cli_clean_exit(capsys):
    code = main(
        [
            str(EXAMPLES / "draft_clean.md"),
            "--bib",
            str(EXAMPLES / "refs.bib"),
            "--year",
            "2026",
        ]
    )
    assert code == 0
    assert "No findings" in capsys.readouterr().out


def test_cli_json(capsys):
    code = main(
        [
            str(EXAMPLES / "draft_clean.md"),
            "--bib",
            str(EXAMPLES / "refs.bib"),
            "--json",
            "--year",
            "2026",
            "--fail-on",
            "never",
        ]
    )
    assert code == 0
    import json

    data = json.loads(capsys.readouterr().out)
    assert data["finding_count"] == 0


def test_cli_missing_file():
    code = main(["/no/such/draft.md", "--bib", str(EXAMPLES / "refs.bib")])
    assert code == 2
