"""Extração local, divisão por capítulo e geração de chunks rastreáveis."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import Destination

MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_PAGES = 1500
CHAPTER_RE = re.compile(r"^(?:cap[ií]tulo|chapter)\s+(?:\d+|[ivxlcdm]+)\b", re.I)
WORD_RE = re.compile(r"\S+")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def pdf_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def choose_pdf(source_dir: Path) -> Path:
    files = sorted(source_dir.glob("*.pdf"))
    if len(files) != 1:
        raise ValueError(f"Esperado exatamente um PDF em {source_dir}; encontrados {len(files)}.")
    pdf = files[0]
    if pdf.stat().st_size > MAX_PDF_BYTES:
        raise ValueError(f"PDF excede o limite de {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    with pdf.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError("Arquivo não tem assinatura PDF válida.")
    return pdf


def extract_pages(reader: PdfReader) -> list[dict[str, Any]]:
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"PDF excede o limite de {MAX_PAGES} páginas.")
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        # O fluxo de texto deste livro preserva a ordem esquerda -> direita.
        # O modo "layout" ordena por posição vertical e intercala as colunas.
        raw = page.extract_text() or ""
        text = "\n".join(" ".join(line.split()) for line in raw.splitlines())
        pages.append({"page": number, "text": text.strip()})
    if sum(len(p["text"]) for p in pages) < 100:
        raise ValueError("Pouco texto extraído. O PDF pode exigir OCR antes da ingestão.")
    return pages


def _outline_chapters(reader: PdfReader) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(items: list[Any]) -> None:
        for item in items:
            if isinstance(item, list):
                visit(item)
            elif isinstance(item, Destination):
                title = " ".join(str(item.title).split())
                if CHAPTER_RE.match(title):
                    found.append({"title": title, "start_page": reader.get_destination_page_number(item) + 1})

    visit(reader.outline)
    return found


def detect_chapters(reader: PdfReader, pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    chapters = _outline_chapters(reader)
    method = "pdf_outline"
    if not chapters:
        method = "heading_heuristic"
        for page in pages:
            for line in page["text"].splitlines()[:12]:
                if CHAPTER_RE.match(line):
                    chapters.append({"title": line[:160], "start_page": page["page"]})
                    break
    by_page: dict[int, dict[str, Any]] = {}
    for chapter in chapters:
        by_page.setdefault(chapter["start_page"], chapter)
    chapters = [by_page[page] for page in sorted(by_page)]
    if not chapters:
        return [{"title": "Capítulo não identificado", "start_page": 1}], "undetected"
    if chapters[0]["start_page"] > 1:
        chapters.insert(0, {"title": "Material inicial", "start_page": 1})
    return chapters, method


def validate_chapters(chapters: list[dict[str, Any]], page_count: int) -> None:
    starts = [chapter["start_page"] for chapter in chapters]
    if not starts or starts[0] != 1 or starts != sorted(set(starts)):
        raise ValueError("chapters.json precisa começar na página 1, em ordem e sem repetição.")
    if starts[-1] > page_count or any(not str(c.get("title", "")).strip() for c in chapters):
        raise ValueError("Capítulo com página fora do PDF ou título vazio.")


def make_chunks(
    pages: list[dict[str, Any]], chapters: list[dict[str, Any]], source_hash: str,
    words_per_chunk: int = 240, overlap_words: int = 40,
) -> list[dict[str, Any]]:
    if words_per_chunk < 1 or overlap_words < 0 or overlap_words >= words_per_chunk:
        raise ValueError("Tamanho de chunk e sobreposição inválidos.")
    validate_chapters(chapters, len(pages))
    chunks = []
    for index, chapter in enumerate(chapters):
        end = chapters[index + 1]["start_page"] if index + 1 < len(chapters) else len(pages) + 1
        words: list[tuple[str, int]] = []
        for page in pages[chapter["start_page"] - 1:end - 1]:
            words.extend((match.group(), page["page"]) for match in WORD_RE.finditer(page["text"]))
        step = words_per_chunk - overlap_words
        for offset in range(0, len(words), step):
            window = words[offset:offset + words_per_chunk]
            if not window:
                continue
            text = " ".join(word for word, _ in window)
            chunk_id = hashlib.sha256(
                f"{source_hash}:{chapter['start_page']}:{offset}:{text}".encode("utf-8")
            ).hexdigest()[:20]
            chunks.append({
                "id": chunk_id,
                "source_sha256": source_hash,
                "chapter": chapter["title"],
                "page_start": window[0][1],
                "page_end": window[-1][1],
                "word_start": offset,
                "text": text,
            })
            if offset + words_per_chunk >= len(words):
                break
    return chunks


def prepare(system_dir: Path) -> dict[str, Any]:
    pdf = choose_pdf(system_dir / "source")
    source_hash = pdf_sha256(pdf)
    reader = PdfReader(str(pdf), strict=False)
    if reader.is_encrypted:
        raise ValueError("PDF criptografado; forneça uma cópia que possa ser lida legalmente.")
    pages = extract_pages(reader)
    chapters, method = detect_chapters(reader, pages)
    output = system_dir / "processed"
    chunks = make_chunks(pages, chapters, source_hash)
    write_jsonl(output / "pages.jsonl", pages)
    write_json(output / "chapters.json", chapters)
    write_jsonl(output / "chunks.jsonl", chunks)
    (output / "embeddings.npy").unlink(missing_ok=True)
    (output / "embeddings.json").unlink(missing_ok=True)
    manifest = {
        "source_file": pdf.name,
        "source_sha256": source_hash,
        "pages": len(pages),
        "chapters": len(chapters),
        "chunks": len(chunks),
        "chapter_detection": method,
        "review_status": "pending",
        "chunk_words": 240,
        "overlap_words": 40,
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def rechunk(system_dir: Path) -> dict[str, Any]:
    output = system_dir / "processed"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    pages = read_jsonl(output / "pages.jsonl")
    chapters = json.loads((output / "chapters.json").read_text(encoding="utf-8"))
    current_hash = pdf_sha256(choose_pdf(system_dir / "source"))
    if current_hash != manifest["source_sha256"]:
        raise ValueError("O PDF mudou. Execute 'prepare' novamente antes de gerar chunks.")
    chunks = make_chunks(pages, chapters, current_hash)
    write_jsonl(output / "chunks.jsonl", chunks)
    (output / "embeddings.npy").unlink(missing_ok=True)
    (output / "embeddings.json").unlink(missing_ok=True)
    manifest.update(chapters=len(chapters), chunks=len(chunks), chapter_detection="manual_review", review_status="pending")
    write_json(output / "manifest.json", manifest)
    return manifest
