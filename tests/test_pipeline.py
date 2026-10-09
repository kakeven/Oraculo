from __future__ import annotations

import json

import pytest
from reportlab.pdfgen import canvas

from pypdf import PdfReader

from oraculo_ingest.pipeline import extract_pages, make_chunks, prepare, read_jsonl, rechunk


def test_prepare_and_rechunk_respect_chapter_pages(tmp_path):
    system = tmp_path / "sample"
    source = system / "source"
    source.mkdir(parents=True)
    pdf = source / "book.pdf"
    doc = canvas.Canvas(str(pdf))
    for title, token in [("Capítulo 1 Regras", "ALFA"), ("Capítulo 2 Personagens", "BETA")]:
        doc.drawString(72, 760, title)
        for line in range(10):
            doc.drawString(72, 730 - line * 18, " ".join([token] * 18))
        doc.showPage()
    doc.save()

    manifest = prepare(system)
    assert manifest["pages"] == 2
    assert manifest["chapters"] == 2
    assert manifest["chapter_detection"] == "heading_heuristic"
    chunks = read_jsonl(system / "processed" / "chunks.jsonl")
    assert chunks
    assert all(c["page_start"] == c["page_end"] for c in chunks)
    assert all(("ALFA" in c["text"]) != ("BETA" in c["text"]) for c in chunks)
    assert all(c["source_sha256"] == manifest["source_sha256"] for c in chunks)

    chapters_path = system / "processed" / "chapters.json"
    chapters_path.write_text(json.dumps([
        {"title": "Abertura", "start_page": 1},
        {"title": "Personagens", "start_page": 2},
    ]), encoding="utf-8")
    updated = rechunk(system)
    assert updated["chapter_detection"] == "manual_review"
    assert read_jsonl(system / "processed" / "chunks.jsonl")[-1]["chapter"] == "Personagens"


def test_chunks_reject_invalid_chapter_map():
    pages = [{"page": 1, "text": "um dois três"}]
    with pytest.raises(ValueError, match="começar na página 1"):
        make_chunks(pages, [{"title": "Dois", "start_page": 2}], "hash")


def test_two_columns_are_read_left_before_right(tmp_path):
    pdf = tmp_path / "columns.pdf"
    doc = canvas.Canvas(str(pdf))
    doc.drawString(70, 750, "Introducao em largura completa " * 5)
    for line in range(5):
        doc.drawString(50, 690 - line * 20, f"ESQUERDA linha {line} conteudo da primeira coluna")
    for line in range(5):
        doc.drawString(310, 690 - line * 20, f"DIREITA linha {line} conteudo da segunda coluna")
    doc.save()
    text = extract_pages(PdfReader(str(pdf)))[0]["text"]
    assert text.index("Introducao") < text.index("ESQUERDA linha 0")
    assert text.index("ESQUERDA linha 4") < text.index("DIREITA linha 0")
