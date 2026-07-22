"""Loader for static reference documents (SOPs, MSDS extracts). CLAUDE.md
§7.1: separate loaders per source type, not one generic loader — this one
handles plain-text/markdown source files. PDF SOPs are explicitly named in
CLAUDE.md §5's tech stack; this project's seed SOPs/MSDS are authored as
markdown (see backend/knowledge/README.md for why), but pypdf is included as
a dependency and load_pdf() is provided so a real PDF SOP can be dropped in
without a design change — it feeds the same chunker downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class RawDocument:
    source_name: str
    source_path: str
    text: str


def load_text_document(path: Path) -> RawDocument:
    text = path.read_text(encoding="utf-8")
    return RawDocument(source_name=path.stem, source_path=str(path), text=text)


def load_pdf_document(path: Path) -> RawDocument:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return RawDocument(source_name=path.stem, source_path=str(path), text=text)


def load_documents_from_dir(directory: Path) -> list[RawDocument]:
    docs: list[RawDocument] = []
    for path in sorted(directory.glob("*")):
        if path.suffix.lower() in (".md", ".txt"):
            docs.append(load_text_document(path))
        elif path.suffix.lower() == ".pdf":
            docs.append(load_pdf_document(path))
    return docs
