import json
import sys
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas

from oraculo_ingest.abilities import build_input, export_prompt, import_result, validate_result
from oraculo_ingest.openai_extractor import extract_with_openai
from oraculo_ingest.pipeline import pdf_sha256, read_jsonl, write_json, write_jsonl


def sample_system(tmp_path):
    system = tmp_path / "sample-system"
    source_dir = system / "source"
    source_dir.mkdir(parents=True)
    pdf = source_dir / "book.pdf"
    doc = canvas.Canvas(str(pdf))
    doc.drawString(70, 750, "Livro de exemplo")
    doc.save()
    processed = system / "processed"
    write_json(processed / "manifest.json", {"source_sha256": pdf_sha256(pdf)})
    write_json(processed / "chapters.json", [{"title": "Capítulo 1: Habilidades", "start_page": 1}])
    write_jsonl(processed / "pages.jsonl", [{
        "page": 1,
        "text": (
            "AS HABILIDADES\n"
            "FORÇA (FOR)\nA Força mede a potência muscular.\n"
            "VIGOR (VIG)\nO Vigor mede a resistência física.\n"
            "HABILIDADES AUMENTADAS\nOutro assunto."
        ),
    }])
    return system


def test_prompt_and_import_validate_model_output(tmp_path):
    system = sample_system(tmp_path)
    preview = export_prompt(system)
    assert preview["headings"] == ["Força (FOR)", "Vigor (VIG)"]
    source = build_input(system)
    assert "Outro assunto" not in source.text

    response = {"abilities": [
        {
            "name": "Força", "abbreviation": "FOR", "description": "Potência muscular.",
            "applications": ["Aplicação descrita na fonte"],
            "evidence_quote": "A Força mede a potência muscular.", "page_pdf": 1,
        },
        {
            "name": "Vigor", "abbreviation": "VIG", "description": "Resistência física.",
            "applications": [],
            "evidence_quote": "O Vigor mede a resistência física.", "page_pdf": 1,
        },
    ]}
    answer_path = tmp_path / "answer.json"
    answer_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    report = import_result(system, answer_path)
    assert report["expected"] == report["received"] == 2
    assert report["records_with_issues"] == 0
    rows = read_jsonl(system / "processed" / "entities" / "habilidades.jsonl")
    assert [r["id"] for r in rows] == [
        "sample-system:habilidade:forca", "sample-system:habilidade:vigor"
    ]
    assert all(r["status"] == "needs_review" for r in rows)


def test_invalid_evidence_is_flagged_and_api_needs_key(tmp_path, monkeypatch):
    source = build_input(sample_system(tmp_path))
    rows, report = validate_result({"abilities": [{
        "name": "Força", "abbreviation": "FOR", "description": "Algo inventado.",
        "applications": [], "evidence_quote": "O Vigor mede a resistência física.", "page_pdf": 1,
    }]}, source)
    assert report["missing"] == [{"name": "Vigor", "abbreviation": "VIG"}]
    assert "citação não encontrada" in rows[0]["issues"][0]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        extract_with_openai(source, "gpt-4o-mini")


def test_openai_adapter_uses_structured_output_without_network(tmp_path, monkeypatch):
    source = build_input(sample_system(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["store"] is False
            assert kwargs["model"] == "gpt-4o-mini"
            assert "FORÇA (FOR)" in kwargs["input"][1]["content"]
            parsed = kwargs["text_format"](abilities=[{
                "name": "Força", "abbreviation": "FOR", "description": "Potência.",
                "applications": [], "evidence_quote": "A Força mede a potência muscular.",
                "page_pdf": 1,
            }])
            return SimpleNamespace(
                output_parsed=parsed,
                usage=SimpleNamespace(input_tokens=100, output_tokens=30),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 60
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    data, usage = extract_with_openai(source, "gpt-4o-mini")
    assert data["abilities"][0]["name"] == "Força"
    assert usage["input_tokens"] == 100
