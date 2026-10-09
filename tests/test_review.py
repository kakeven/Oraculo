import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from oraculo_ingest.pipeline import pdf_sha256, write_jsonl
from oraculo_ingest.review_server import make_handler
from oraculo_ingest.review_store import current_rows, decisions, fingerprint, set_decision, set_text, state


def review_system(tmp_path):
    system = tmp_path / "systems" / "sample-system"
    source = system / "source"
    source.mkdir(parents=True)
    pdf = source / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    row = {
        "id": "sample-system:skill:acrobacia", "type": "skill", "name": "Acrobacia",
        "subtype": "", "source_sha256": pdf_sha256(pdf), "page_start": 4,
        "line_start": 2, "page_end": 4, "line_end": 5,
        "text": "ACROBACIA\n<img onerror=alert(1)>\nRegra da perícia.", "status": "needs_review",
    }
    write_jsonl(system / "processed" / "entities" / "catalog.jsonl", [row])
    return system, row


def test_approval_persists_only_for_exact_source(tmp_path):
    system, row = review_system(tmp_path)
    assert state(row, decisions(system)) == "needs_review"
    event = set_decision(system, row["id"], "approved", fingerprint(row))
    assert event["decision"] == "approved"
    assert state(row, decisions(system)) == "approved"
    changed = {**row, "text": row["text"] + "\nNova linha."}
    assert state(changed, decisions(system)) == "needs_review"
    write_jsonl(system / "processed" / "entities" / "catalog.jsonl", [changed])
    with pytest.raises(RuntimeError, match="texto mudou"):
        set_decision(system, row["id"], "approved", fingerprint(row))
    set_decision(system, row["id"], "approved", fingerprint(changed))
    assert state(changed, decisions(system)) == "approved"
    set_decision(system, row["id"], "needs_review", fingerprint(changed))
    assert state(changed, decisions(system)) == "needs_review"


def test_edit_overwrites_effective_text_and_preserves_original(tmp_path):
    system, raw = review_system(tmp_path)
    set_decision(system, raw["id"], "approved", fingerprint(raw))
    edited = set_text(system, raw["id"], "ACROBACIA\nRegra corrigida.", fingerprint(raw))
    assert edited["text"] == "ACROBACIA\nRegra corrigida."
    assert edited["original_text"] == raw["text"]
    assert edited["edited"] is True
    assert edited["state"] == "needs_review"
    assert current_rows(system)[0]["text"] == edited["text"]
    catalog = json.loads((system / "processed" / "entities" / "catalog.jsonl").read_text(encoding="utf-8"))
    assert catalog["text"] == raw["text"]
    with pytest.raises(RuntimeError, match="texto mudou"):
        set_text(system, raw["id"], "Outra edição", fingerprint(raw))
    set_decision(system, raw["id"], "approved", edited["fingerprint"])
    assert state(current_rows(system)[0], decisions(system)) == "approved"
    restored = set_text(system, raw["id"], raw["text"], edited["fingerprint"])
    assert restored["edited"] is False
    changed = {**raw, "text": "Nova extração"}
    write_jsonl(system / "processed" / "entities" / "catalog.jsonl", [changed])
    assert current_rows(system)[0]["text"] == "Nova extração"


def test_edit_requires_nonempty_text(tmp_path):
    system, raw = review_system(tmp_path)
    with pytest.raises(ValueError, match="texto deve"):
        set_text(system, raw["id"], "  ", fingerprint(raw))


def test_review_http_requires_session_and_same_origin_for_changes(tmp_path):
    system, row = review_system(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    server.RequestHandlerClass = make_handler(system, server.server_port, "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/") as response:
            html = response.read().decode("utf-8")
            assert "test-token" in html
            assert "<img onerror" not in html
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        with urllib.request.urlopen(base + "/source.pdf") as response:
            assert response.headers["Content-Type"] == "application/pdf"
            assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
            assert response.read().startswith(b"%PDF-")
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(base + "/api/catalog")
        assert missing.value.code == 403

        listing = urllib.request.Request(base + "/api/catalog", headers={"X-Oraculo-Token": "test-token"})
        with urllib.request.urlopen(listing) as response:
            assert json.load(response)[0]["state"] == "needs_review"
            assert response.headers["X-Content-Type-Options"] == "nosniff"

        payload = json.dumps({"decision": "approved", "fingerprint": fingerprint(row)}).encode()
        wrong_origin = urllib.request.Request(
            base + "/api/items/" + row["id"] + "/review", data=payload, method="POST",
            headers={"X-Oraculo-Token": "test-token", "Origin": "https://example.test",
                     "Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as forbidden:
            urllib.request.urlopen(wrong_origin)
        assert forbidden.value.code == 403
        assert state(row, decisions(system)) == "needs_review"

        valid = urllib.request.Request(
            base + "/api/items/" + row["id"] + "/review", data=payload, method="POST",
            headers={"X-Oraculo-Token": "test-token", "Origin": base,
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(valid) as response:
            assert json.load(response)["decision"] == "approved"
        assert state(row, decisions(system)) == "approved"

        edit_payload = json.dumps({"text": "ACROBACIA\nTexto limpo.",
                                   "fingerprint": fingerprint(row)}).encode()
        edit_url = base + "/api/items/" + row["id"] + "/text"
        wrong_edit = urllib.request.Request(edit_url, data=edit_payload, method="PUT",
            headers={"X-Oraculo-Token": "test-token", "Origin": "https://example.test",
                     "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as forbidden_edit:
            urllib.request.urlopen(wrong_edit)
        assert forbidden_edit.value.code == 403
        valid_edit = urllib.request.Request(edit_url, data=edit_payload, method="PUT",
            headers={"X-Oraculo-Token": "test-token", "Origin": base,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(valid_edit) as response:
            saved = json.load(response)
        assert saved["text"] == "ACROBACIA\nTexto limpo."
        assert saved["state"] == "needs_review"
        assert saved["edited"] is True
        with urllib.request.urlopen(urllib.request.Request(base + "/api/items/" + row["id"],
                                  headers={"X-Oraculo-Token": "test-token"})) as response:
            assert json.load(response)["original_text"] == row["text"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
