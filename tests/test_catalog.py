from oraculo_ingest.catalog import find_entities, index_entities, load_entities
from oraculo_ingest.pipeline import pdf_sha256, write_json, write_jsonl


def test_catalog_separates_named_sections_and_keeps_source_positions(tmp_path):
    system = tmp_path / "example"
    source = system / "source"
    source.mkdir(parents=True)
    pdf = source / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    digest = pdf_sha256(pdf)
    processed = system / "processed"
    write_json(processed / "manifest.json", {"source_sha256": digest})
    write_jsonl(processed / "pages.jsonl", [
        {"page": 57, "text": "FORÇA (FOR)\nRegra da força.\nVIGOR (VIG)\nRegra do vigor."},
        {"page": 64, "text": "ACROBACIA\nRegra acrobática.\nCAMBALHOTAS\nDetalhe."},
        {"page": 65, "text": "ATLETISMO\nRegra atlética."},
        {"page": 78, "text": "AGARRAR RÁPIDO COMBATE\nRegra da vantagem."},
        {"page": 95, "text": "DANO ATAQUE\nAção: padrão\nRegra de dano.\nIMPEDIR MOVIMENTO\nSubtítulo, não é efeito.\nGOLPE\nEfeito: Dano"},
        {"page": 96, "text": "VOO MOVIMENTO\nAção: livre\nRegra de voo."},
    ])
    report = index_entities(system)
    assert report["counts"] == {"ability": 2, "skill": 2, "advantage": 1,
                                "effect": 2, "power_example": 1}
    rows = load_entities(system, digest)
    acrobatics = next(row for row in rows if row["name"] == "Acrobacia")
    assert acrobatics["page_start"] == 64
    assert "Regra atlética" not in acrobatics["text"]
    assert find_entities(rows, "Quero voar", kind="effect")[0]["name"] == "Voo"
    assert not any(row["name"] == "Impedir" for row in rows)
