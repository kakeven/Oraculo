import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from oraculo_ingest.pipeline import pdf_sha256, write_json, write_jsonl
from oraculo_ingest.qa import ask_with_chatgpt, ask_with_oraculo_login, build_prompt
from oraculo_ingest.review_store import fingerprint, set_decision, set_text


def sample_system(tmp_path):
    system = tmp_path / "systems" / "sample-system"
    source = system / "source"
    source.mkdir(parents=True)
    pdf = source / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    digest = pdf_sha256(pdf)
    processed = system / "processed"
    write_json(processed / "manifest.json", {"source_sha256": digest})
    write_jsonl(processed / "chunks.jsonl", [{
        "id": "chunk1", "chapter": "Combate", "page_start": 4, "page_end": 4,
        "text": "Agarrar usa uma ação padrão e exige um teste de ataque.",
    }])
    write_jsonl(processed / "entities" / "rules.jsonl", [{
        "name": "Agarrar", "page_pdf": 4, "status": "needs_review",
        "source_sha256": digest, "summary": "Agarrar é ação padrão.",
        "evidence_quote": "Agarrar usa uma ação padrão",
    }])
    return system


def test_prompt_uses_local_evidence_and_rejects_stale_rules(tmp_path):
    system = sample_system(tmp_path)
    prompt = build_prompt(system, "Posso agarrar?")
    assert "PDF p. 4" in prompt
    assert "Agarrar é ação padrão" in prompt
    assert "Posso agarrar?" in prompt
    rules_path = system / "processed" / "entities" / "rules.jsonl"
    row = json.loads(rules_path.read_text(encoding="utf-8"))
    row["source_sha256"] = "outro"
    write_jsonl(rules_path, [row])
    with pytest.raises(ValueError, match="outra versão"):
        build_prompt(system, "Posso agarrar?")


def test_priority_rule_includes_verified_page_window(tmp_path):
    system = sample_system(tmp_path)
    processed = system / "processed"
    write_jsonl(processed / "pages.jsonl", [{
        "page": 4, "text": "Capítulo Combate. AGARRAR AÇÃO PADRÃO. Faça um teste de ataque.",
    }])
    rules_path = processed / "entities" / "rules.jsonl"
    row = json.loads(rules_path.read_text(encoding="utf-8"))
    row["evidence_quote"] = "AGARRAR AÇÃO PADRÃO"
    row["source_priority"] = 100
    write_jsonl(rules_path, [row])
    prompt = build_prompt(system, "Posso agarrar?")
    assert "PDF p. 4, Agarrar: " in prompt
    assert "Faça um teste de ataque" in prompt
    assert prompt.count("- PDF p. ") == 1


def test_ask_uses_chatgpt_login_and_read_only_codex(tmp_path, monkeypatch):
    system = sample_system(tmp_path)
    monkeypatch.setattr("oraculo_ingest.qa.shutil.which", lambda _: "codex.exe")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:3] == ["login", "status"]:
            return SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")
        Path(command[command.index("-o") + 1]).write_text("Agarrar usa ação padrão (PDF p. 4).", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("oraculo_ingest.qa.subprocess.run", fake_run)
    with pytest.raises(ValueError, match="--allow-external-processing"):
        ask_with_chatgpt(system, "Posso agarrar?")
    assert "PDF p. 4" in ask_with_chatgpt(system, "Posso agarrar?", allow_external_processing=True)
    command, kwargs = calls[1]
    assert command[:2] == ["codex", "exec"]
    assert "read-only" in command and "--ephemeral" in command
    assert command[-1] == "-" and "Posso agarrar?" in kwargs["input"]


def test_ask_with_oraculo_login_sends_local_evidence_only_when_authorized(tmp_path, monkeypatch):
    system = sample_system(tmp_path)
    calls = []
    monkeypatch.setattr("oraculo_ingest.qa.chatgpt_auth.answer",
                        lambda prompt, model=None: calls.append((prompt, model)) or "Resposta")
    with pytest.raises(ValueError, match="--allow-external-processing"):
        ask_with_oraculo_login(system, "Posso agarrar?")
    assert calls == []
    assert ask_with_oraculo_login(system, "Posso agarrar?", model="selected",
                                  allow_external_processing=True) == "Resposta"
    assert "PDF p. 4" in calls[0][0]
    assert calls[0][1] == "selected"


def test_catalog_question_omits_unrelated_pilot_rules(tmp_path):
    system = sample_system(tmp_path)
    row = {
        "id": "sample:skill:acrobacia", "type": "skill", "name": "Acrobacia",
        "source_sha256": pdf_sha256(system / "source" / "book.pdf"),
        "page_start": 8, "line_start": 2, "page_end": 8, "line_end": 150,
        "status": "needs_review",
        "text": "ACROBACIA\n" + "Descrição da perícia.\n" * 130 +
                "MANOBRAR\nO mestre define a CD da manobra.",
    }
    write_jsonl(system / "processed" / "entities" / "catalog.jsonl", [row])
    prompt = build_prompt(system, "Como funciona Acrobacia?")
    assert "ACROBACIA" in prompt
    assert "Agarrar é ação padrão" not in prompt
    assert "PDF p. 8-8" in prompt
    assert "O mestre define a CD da manobra" in prompt
    set_decision(system, row["id"], "approved", fingerprint(row))
    assert "PDF p. 8-8, approved" in build_prompt(system, "Como funciona Acrobacia?")
    edited = set_text(system, row["id"], "ACROBACIA\nTexto revisado.", fingerprint(row))
    prompt = build_prompt(system, "Como funciona Acrobacia?")
    assert "Texto revisado." in prompt
    assert "O mestre define a CD da manobra" not in prompt
    assert "PDF p. 8-8, needs_review" in prompt
    set_decision(system, row["id"], "approved", edited["fingerprint"])
    assert "PDF p. 8-8, approved" in build_prompt(system, "Como funciona Acrobacia?")
