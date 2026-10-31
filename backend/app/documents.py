"""Document retrieval, page-level text extraction and lexical retrieval.

* PDFs are downloaded once; bytes are hashed so unchanged documents are never re-parsed.
* Text is reconstructed row-by-row from word coordinates, which keeps a results-table row (label + numbers)
  on one line - the property the results extractor relies on.
* Retrieval is BM25 over page chunks. For a handful of documents per company that is cheaper, more transparent
  and easier to cite (page numbers) than embeddings + a vector DB.
"""
from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pymupdf as fitz  # PyMuPDF

from . import storage
from .config import settings
from .http import SourceError, fetch, make_client

log = logging.getLogger("finn.documents")
FIXTURE_DOCS = Path(__file__).resolve().parent / "fixtures" / "docs"
REUSE_S = 7 * 86400
PARSER_VERSION = "2"  # bump when page-text extraction changes so cached parses are rebuilt


@dataclass
class Doc:
    url: str
    status: str            # ok | no_text_layer | error
    pages: list[str]
    detail: str = ""
    sha256: str = ""


def _rows_from_page(page: "fitz.Page") -> str:
    words = page.get_text("words")
    if not words:
        return ""
    words.sort(key=lambda w: (round((w[1] + w[3]) / 2), w[0]))
    rows: list[list[tuple]] = []
    for w in words:
        yc = (w[1] + w[3]) / 2
        if rows and abs(((rows[-1][0][1] + rows[-1][0][3]) / 2) - yc) <= 3.0:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        # Some PDFs draw each word twice with a tiny offset ("fake bold"): drop a word identical to the previous one
        # that overlaps it horizontally.
        dedup = []
        for w in r:
            if dedup and w[4] == dedup[-1][4] and w[0] < dedup[-1][2] - 0.5:
                continue
            dedup.append(w)
        r = dedup
        parts, prev_x1 = [], None
        for w in r:
            if prev_x1 is not None and w[0] - prev_x1 > 8:
                parts.append("  ")
            elif prev_x1 is not None:
                parts.append(" ")
            parts.append(w[4])
            prev_x1 = w[2]
        lines.append("".join(parts))
    return "\n".join(lines)


def pdf_bytes_to_pages(data: bytes) -> list[str]:
    with fitz.open(stream=data, filetype="pdf") as d:
        return [_rows_from_page(p) for p in d]


def get_document(url: str) -> Doc:
    key = f"v{PARSER_VERSION}|{url}"
    cached = storage.doc_get(key)
    if cached and cached["pages"] is not None and time.time() - cached["fetched"] < REUSE_S:
        return _wrap(url, cached["pages"], cached["sha256"])
    try:
        if settings.fixture_mode:
            name = Path(urlparse(url).path).name
            path = FIXTURE_DOCS / name
            if not path.exists():
                return Doc(url, "error", [], "fixture document not found")
            data, ctype = path.read_bytes(), "application/pdf"
        else:
            with make_client() as c:
                r = fetch(c, url, "document", allow_external_documents=True, max_bytes=settings.max_pdf_mb * 1024 * 1024)
            data, ctype = r.content, r.headers.get("content-type", "")
    except SourceError as e:
        return Doc(url, "error", [], e.message)
    sha = storage.sha256(data)
    if cached and cached["sha256"] == sha and cached["pages"] is not None:
        storage.doc_put(key, sha, ctype, len(data), cached["pages"])
        return _wrap(url, cached["pages"], sha)
    if not data.startswith(b"%PDF"):
        if "html" in ctype or data[:200].lower().find(b"<html") >= 0:
            return Doc(url, "error", [], "source returned an HTML page instead of the PDF (blocked or moved)")
        return Doc(url, "error", [], f"unsupported content type: {ctype or 'unknown'}")
    try:
        pages = pdf_bytes_to_pages(data)
    except Exception as e:  # malformed PDF
        log.warning("pdf parse failed %s: %s", url, e)
        return Doc(url, "error", [], "PDF could not be parsed")
    storage.doc_put(key, sha, ctype, len(data), pages)
    return _wrap(url, pages, sha)


def _wrap(url: str, pages: list[str], sha: str) -> Doc:
    if not any(p.strip() for p in pages):
        return Doc(url, "no_text_layer", pages, "scanned PDF without a text layer (OCR not supported)", sha)
    return Doc(url, "ok", pages, f"{len(pages)} pages", sha)


# ---------------------------------------------------------------- retrieval

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = set("the of and to in a for is on that with as by at from this are be or an it we our has have will was were which their its".split())


def tokens(s: str) -> list[str]:
    return [t for t in _TOKEN.findall(s.lower()) if t not in _STOP and len(t) > 1]


@dataclass
class Chunk:
    doc_id: str      # short id used in citations, e.g. "T3"
    page: int        # 1-based
    text: str


def chunk_pages(doc_id: str, pages: list[str], size: int = 1400, overlap: int = 200) -> list[Chunk]:
    out = []
    for i, p in enumerate(pages, 1):
        p = re.sub(r"[ \t]+", " ", p).strip()
        if len(p) < 80:
            continue
        start = 0
        while start < len(p):
            out.append(Chunk(doc_id, i, p[start:start + size]))
            if start + size >= len(p):
                break
            start += size - overlap
    return out


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks = chunks
        self.toks = [tokens(c.text) for c in chunks]
        self.df: Counter = Counter()
        for t in self.toks:
            self.df.update(set(t))
        self.n = len(chunks)
        self.avg = sum(len(t) for t in self.toks) / self.n if self.n else 0
        self.tf = [Counter(t) for t in self.toks]
        self.k1, self.b = k1, b

    def search(self, query: str, k: int = 6, doc_ids: set[str] | None = None) -> list[tuple[float, Chunk]]:
        q = tokens(query)
        scored = []
        for i, c in enumerate(self.chunks):
            if doc_ids and c.doc_id not in doc_ids:
                continue
            s = 0.0
            dl = len(self.toks[i]) or 1
            for t in q:
                f = self.tf[i].get(t)
                if not f:
                    continue
                idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avg or 1)))
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]
