import json

from oraculo_ingest.pipeline import pdf_sha256, read_jsonl, write_json, write_jsonl
from oraculo_ingest.rules import import_rules


def test_rule_import_requires_page_evidence_and_preserves_last_valid_output(tmp_path):
    system = tmp_path / "sample-system"
    source = system / "source"
    source.mkdir(parents=True)
    pdf = source / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    digest = pdf_sha256(pdf)
    processed = system / "processed"
    write_json(processed / "manifest.json", {"source_sha256": digest})
    write_jsonl(processed / "pages.jsonl", [{"page": 1, "text": "AGARRAR AÇÃO PADRÃO\nFaça um teste de ataque."}])
    input_file = tmp_path / "input.json"
    payload = {"source_sha256": digest, "rules": [{
        "id": "agarrar", "name": "Agarrar", "category": "combat_action",
        "summary": "Ação padrão para agarrar um alvo.", "page_pdf": 1,
        "evidence_quote": "AGARRAR AÇÃO PADRÃO",
    }]}
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    assert import_rules(system, input_file)["valid_provenance"] == 1
    output = processed / "entities" / "rules.jsonl"
    assert read_jsonl(output)[0]["status"] == "needs_review"
    original = output.read_bytes()

    payload["rules"][0]["evidence_quote"] = "Esta regra não aparece na página"
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    report = import_rules(system, input_file)
    assert report["valid_provenance"] == 0
    assert "citação não encontrada" in report["issues"][0]["issue"]
    assert output.read_bytes() == original
