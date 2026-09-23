"""Core analysis: recency phrases near citations vs BibTeX years."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

# Word-boundary recency language (case-insensitive).
RECENCY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("state of the art", re.compile(r"\bstate\s+of\s+the\s+art\b", re.I)),
    ("state-of-the-art", re.compile(r"\bstate-of-the-art\b", re.I)),
    ("cutting-edge", re.compile(r"\bcutting-edge\b", re.I)),
    ("recently", re.compile(r"\brecently\b", re.I)),
    ("recent", re.compile(r"\brecent\b", re.I)),
    ("SOTA", re.compile(r"\bSOTA\b")),
    ("latest", re.compile(r"\blatest\b", re.I)),
    ("newly", re.compile(r"\bnewly\b", re.I)),
]

# Markdown pandoc-style: [@key], [@key1;@key2], [@key1; @key2]
MD_CITE_RE = re.compile(
    r"\[@([A-Za-z0-9_:.+\-/]+)(?:\s*;\s*@([A-Za-z0-9_:.+\-/]+))*\]"
)

# Broader MD capture for multi-key braces content
MD_CITE_BLOCK_RE = re.compile(r"\[(@[^\[\]]+)\]")

# LaTeX cite commands
LATEX_CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|Cite|Citep|Citet|parencite|textcite|autocite)"
    r"(?:\[[^\]]*\]){0,2}\{([^}]+)\}"
)

# Sentence boundary heuristic
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# BibTeX entry start
BIB_ENTRY_RE = re.compile(
    r"@(?P<type>\w+)\s*\{\s*(?P<key>[^,}\s]+)\s*,",
    re.I,
)
# year field: year = {2020} or year = 2020
YEAR_FIELD_RE = re.compile(
    r"(?i)\byear\s*=\s*(?:\{([^}]*)\}|\"([^\"]*)\"|(\d{4}))",
)

NEAR_CHARS = 400
NEAR_SENTENCES = 2


@dataclass
class PhraseHit:
    phrase: str
    start: int
    end: int
    line: int
    text: str


@dataclass
class CiteHit:
    keys: list[str]
    start: int
    end: int
    line: int
    raw: str


@dataclass
class Finding:
    kind: str  # stale | no_year | no_citation
    path: str
    line: int
    phrase: str
    phrase_span: tuple[int, int]
    citation_keys: list[str] = field(default_factory=list)
    years: dict[str, int | None] = field(default_factory=dict)
    detail: str = ""
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    findings: list[Finding]
    current_year: int
    max_age: int
    cutoff_year: int
    files_scanned: list[str]
    bib_entries: int
    errors: list[str] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_year": self.current_year,
            "max_age": self.max_age,
            "cutoff_year": self.cutoff_year,
            "files_scanned": self.files_scanned,
            "bib_entries": self.bib_entries,
            "errors": self.errors,
            "finding_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
        }


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def parse_bibtex(text: str) -> dict[str, int | None]:
    """Return map of citation key -> year (or None if missing/unparseable)."""
    years: dict[str, int | None] = {}
    matches = list(BIB_ENTRY_RE.finditer(text))
    for i, m in enumerate(matches):
        key = m.group("key").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        ym = YEAR_FIELD_RE.search(body)
        if not ym:
            years[key] = None
            continue
        raw = (ym.group(1) or ym.group(2) or ym.group(3) or "").strip()
        # Extract first 4-digit year
        ym4 = re.search(r"(\d{4})", raw)
        if ym4:
            years[key] = int(ym4.group(1))
        else:
            years[key] = None
    return years


def find_recency_phrases(text: str) -> list[PhraseHit]:
    hits: list[PhraseHit] = []
    occupied: list[tuple[int, int]] = []
    # Longer / more specific patterns first (already ordered)
    for label, pat in RECENCY_PATTERNS:
        for m in pat.finditer(text):
            span = (m.start(), m.end())
            if any(not (span[1] <= a or span[0] >= b) for a, b in occupied):
                continue
            occupied.append(span)
            snippet = text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " ")
            hits.append(
                PhraseHit(
                    phrase=label,
                    start=m.start(),
                    end=m.end(),
                    line=_line_of(text, m.start()),
                    text=snippet.strip(),
                )
            )
    hits.sort(key=lambda h: h.start)
    return hits


def _keys_from_md_block(inner: str) -> list[str]:
    # inner like "@smith2020; @jones2018" or "@a;@b"
    keys: list[str] = []
    for part in inner.split(";"):
        part = part.strip()
        if part.startswith("@"):
            part = part[1:]
        part = part.strip()
        if part:
            keys.append(part)
    return keys


def find_citations(text: str) -> list[CiteHit]:
    hits: list[CiteHit] = []
    seen_spans: set[tuple[int, int]] = set()

    for m in MD_CITE_BLOCK_RE.finditer(text):
        inner = m.group(1)
        if not inner.lstrip().startswith("@"):
            continue
        keys = _keys_from_md_block(inner)
        if not keys:
            continue
        span = (m.start(), m.end())
        if span in seen_spans:
            continue
        seen_spans.add(span)
        hits.append(
            CiteHit(
                keys=keys,
                start=m.start(),
                end=m.end(),
                line=_line_of(text, m.start()),
                raw=m.group(0),
            )
        )

    for m in LATEX_CITE_RE.finditer(text):
        keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
        if not keys:
            continue
        span = (m.start(), m.end())
        if span in seen_spans:
            continue
        seen_spans.add(span)
        hits.append(
            CiteHit(
                keys=keys,
                start=m.start(),
                end=m.end(),
                line=_line_of(text, m.start()),
                raw=m.group(0),
            )
        )

    hits.sort(key=lambda h: h.start)
    return hits


def _sentence_windows(text: str) -> list[tuple[int, int]]:
    """Return (start, end) char spans for approximate sentences."""
    parts = SENT_SPLIT_RE.split(text)
    windows: list[tuple[int, int]] = []
    pos = 0
    for part in parts:
        if not part:
            continue
        # Find actual location (handle whitespace eaten by split carefully)
        idx = text.find(part, pos)
        if idx < 0:
            idx = pos
        end = idx + len(part)
        windows.append((idx, end))
        pos = end
    if not windows and text:
        windows.append((0, len(text)))
    return windows


def _paragraph_span(text: str, index: int) -> tuple[int, int]:
    """Return (start, end) of the blank-line-delimited paragraph containing index."""
    # Find preceding blank line
    start = 0
    for m in re.finditer(r"\n\s*\n", text):
        if m.end() <= index:
            start = m.end()
        else:
            break
    end = len(text)
    for m in re.finditer(r"\n\s*\n", text):
        if m.start() > index:
            end = m.start()
            break
    return start, end


def _no_blank_between(text: str, a: int, b: int) -> bool:
    lo, hi = (a, b) if a <= b else (b, a)
    return re.search(r"\n\s*\n", text[lo:hi]) is None


def _nearby_citations(
    phrase: PhraseHit,
    cites: list[CiteHit],
    text: str,
) -> list[CiteHit]:
    """Citations near a phrase: same paragraph, or within ~2 sentences/~400 chars
    without crossing a blank-line paragraph boundary.
    """
    nearby: list[CiteHit] = []
    para_lo, para_hi = _paragraph_span(text, phrase.start)
    windows = _sentence_windows(text)

    p_sent = 0
    for i, (s, e) in enumerate(windows):
        if s <= phrase.start < e:
            p_sent = i
            break
        if phrase.start < s:
            p_sent = max(0, i - 1)
            break
        p_sent = i

    sent_lo = max(0, p_sent - NEAR_SENTENCES)
    sent_hi = min(len(windows) - 1, p_sent + NEAR_SENTENCES) if windows else 0
    if windows:
        win_start = windows[sent_lo][0]
        win_end = windows[sent_hi][1]
    else:
        win_start, win_end = 0, len(text)

    char_lo = max(0, phrase.start - NEAR_CHARS)
    char_hi = min(len(text), phrase.end + NEAR_CHARS)

    for c in cites:
        # Same paragraph always counts
        if para_lo <= c.start < para_hi or para_lo < c.end <= para_hi:
            nearby.append(c)
            continue
        # Otherwise: must not cross blank lines, and must be in sentence or char window
        if not _no_blank_between(text, phrase.start, c.start):
            continue
        in_sent = not (c.end < win_start or c.start > win_end)
        in_chars = not (c.end < char_lo or c.start > char_hi)
        if in_sent or in_chars:
            nearby.append(c)
    return nearby


def analyze_text(
    text: str,
    path: str,
    bib_years: dict[str, int | None],
    *,
    current_year: int,
    max_age: int,
) -> list[Finding]:
    cutoff = current_year - max_age
    phrases = find_recency_phrases(text)
    cites = find_citations(text)
    findings: list[Finding] = []

    for phrase in phrases:
        near = _nearby_citations(phrase, cites, text)
        if not near:
            ctx = text[max(0, phrase.start - 40) : phrase.end + 40].replace("\n", " ")
            findings.append(
                Finding(
                    kind="no_citation",
                    path=path,
                    line=phrase.line,
                    phrase=phrase.phrase,
                    phrase_span=(phrase.start, phrase.end),
                    detail="recency phrase has no nearby citation",
                    context=ctx.strip(),
                )
            )
            continue

        keys: list[str] = []
        for c in near:
            keys.extend(c.keys)
        # unique preserve order
        seen: set[str] = set()
        uniq_keys: list[str] = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                uniq_keys.append(k)

        year_map: dict[str, int | None] = {}
        for k in uniq_keys:
            year_map[k] = bib_years.get(k)  # None if missing from bib OR no year

        missing_from_bib = [k for k in uniq_keys if k not in bib_years]
        no_year_keys = [
            k for k in uniq_keys if k in bib_years and bib_years[k] is None
        ]
        # Treat missing-from-bib as no_year for reporting
        no_year_keys = list(dict.fromkeys(no_year_keys + missing_from_bib))

        stale_keys = [
            k
            for k in uniq_keys
            if bib_years.get(k) is not None and bib_years[k] < cutoff  # type: ignore[operator]
        ]

        ctx = text[max(0, phrase.start - 40) : phrase.end + 80].replace("\n", " ")

        if stale_keys:
            ages = {
                k: current_year - bib_years[k]  # type: ignore[operator]
                for k in stale_keys
            }
            detail = (
                f"recency phrase near citation(s) older than {max_age} years "
                f"(cutoff year {cutoff}): "
                + ", ".join(f"{k}={bib_years[k]}" for k in stale_keys)
                + f" ages={ages}"
            )
            findings.append(
                Finding(
                    kind="stale",
                    path=path,
                    line=phrase.line,
                    phrase=phrase.phrase,
                    phrase_span=(phrase.start, phrase.end),
                    citation_keys=stale_keys,
                    years={k: bib_years.get(k) for k in stale_keys},
                    detail=detail,
                    context=ctx.strip(),
                )
            )

        if no_year_keys:
            findings.append(
                Finding(
                    kind="no_year",
                    path=path,
                    line=phrase.line,
                    phrase=phrase.phrase,
                    phrase_span=(phrase.start, phrase.end),
                    citation_keys=no_year_keys,
                    years={k: bib_years.get(k) for k in no_year_keys},
                    detail="nearby citation(s) missing year in BibTeX (or not in bib)",
                    context=ctx.strip(),
                )
            )

    return findings


def scan(
    draft_paths: Iterable[Path],
    bib_path: Path,
    *,
    max_age: int = 5,
    current_year: int | None = None,
) -> ScanResult:
    """Scan drafts against a BibTeX file for stale recency claims."""
    cy = current_year if current_year is not None else date.today().year
    errors: list[str] = []
    findings: list[Finding] = []
    files_scanned: list[str] = []
    bib_years: dict[str, int | None] = {}

    try:
        bib_text = bib_path.read_text(encoding="utf-8")
        bib_years = parse_bibtex(bib_text)
    except OSError as exc:
        errors.append(f"cannot read bib: {bib_path}: {exc}")
        return ScanResult(
            findings=[],
            current_year=cy,
            max_age=max_age,
            cutoff_year=cy - max_age,
            files_scanned=[],
            bib_entries=0,
            errors=errors,
        )

    for path in draft_paths:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read draft: {p}: {exc}")
            continue
        files_scanned.append(str(p))
        findings.extend(
            analyze_text(
                text,
                str(p),
                bib_years,
                current_year=cy,
                max_age=max_age,
            )
        )

    return ScanResult(
        findings=findings,
        current_year=cy,
        max_age=max_age,
        cutoff_year=cy - max_age,
        files_scanned=files_scanned,
        bib_entries=len(bib_years),
        errors=errors,
    )


def format_human(result: ScanResult) -> str:
    lines: list[str] = []
    lines.append(
        f"refage: cutoff year {result.cutoff_year} "
        f"(current {result.current_year}, max-age {result.max_age}); "
        f"{result.bib_entries} bib entries; "
        f"{len(result.files_scanned)} file(s)"
    )
    if result.errors:
        for e in result.errors:
            lines.append(f"ERROR: {e}")
    if not result.findings:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"

    by_kind = {"stale": 0, "no_year": 0, "no_citation": 0}
    for f in result.findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        keys = ", ".join(f.citation_keys) if f.citation_keys else "-"
        years = (
            ", ".join(f"{k}={v}" for k, v in f.years.items()) if f.years else "-"
        )
        lines.append(
            f"[{f.kind}] {f.path}:{f.line} phrase={f.phrase!r} "
            f"keys={keys} years={years}"
        )
        if f.detail:
            lines.append(f"  {f.detail}")
        if f.context:
            lines.append(f"  context: {f.context}")

    lines.append(
        f"Summary: {len(result.findings)} finding(s) "
        f"(stale={by_kind.get('stale', 0)}, "
        f"no_year={by_kind.get('no_year', 0)}, "
        f"no_citation={by_kind.get('no_citation', 0)})"
    )
    return "\n".join(lines) + "\n"
