"""Importação verificável de regras estruturadas de um livro já processado."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .pipeline import choose_pdf, pdf_sha256, read_jsonl, write_json, write_jsonl


REQUIRED = {"id", "name", "category", "summary", "page_pdf", "evidence_quote"}
CATEGORIES = {"action_economy", "movement", "combat_action", "advantage", "effect", "defense"}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold().strip()


def import_rules(system_dir: Path, input_path: Path) -> dict[str, Any]:
    """Validate provenance, then store proposed rules for human mechanical review.

    Exact source quotes prove a rule points to a real page, not that its summary
    correctly interprets the mechanics. No rule is marked approved here.
    """
    processed = system_dir / "processed"
    manifest = json.loads((processed / "manifest.json").read_text(encoding="utf-8"))
    source_hash = pdf_sha256(choose_pdf(system_dir / "source"))
    if source_hash != manifest["source_sha256"]:
        raise ValueError("O PDF mudou. Execute 'prepare' antes de importar regras.")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("source_sha256") != source_hash:
        raise ValueError("O hash da fonte no arquivo de regras não corresponde ao PDF.")
    candidates = payload.get("rules")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("O arquivo precisa conter uma lista não vazia de regras.")
    pages = {page["page"]: page["text"] for page in read_jsonl(processed / "pages.jsonl")}
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    system_slug = system_dir.name
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            issues.append({"rule": str(index), "issue": "registro não é um objeto"})
            continue
        missing = REQUIRED - candidate.keys()
        if missing:
            issues.append({"rule": str(index), "issue": f"campos ausentes: {sorted(missing)}"})
            continue
        rule_id = candidate["id"]
        page_number = candidate["page_pdf"]
        quote = candidate["evidence_quote"]
        if not isinstance(rule_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", rule_id) or rule_id in seen:
            issues.append({"rule": str(index), "issue": "id inválido ou repetido"})
            continue
        seen.add(rule_id)
        if not isinstance(candidate["category"], str) or candidate["category"] not in CATEGORIES:
            issues.append({"rule": rule_id, "issue": "categoria inválida"})
            continue
        if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number not in pages:
            issues.append({"rule": rule_id, "issue": "página PDF inválida"})
            continue
        if not isinstance(quote, str) or len(quote.strip()) < 15 or _normalize(quote) not in _normalize(pages[page_number]):
            issues.append({"rule": rule_id, "issue": "citação não encontrada na página indicada"})
            continue
        if not all(isinstance(candidate[key], str) and candidate[key].strip() for key in ("name", "summary")):
            issues.append({"rule": rule_id, "issue": "nome ou resumo vazio"})
            continue
        priority = candidate.get("source_priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 100:
            issues.append({"rule": rule_id, "issue": "prioridade da fonte inválida"})
            continue
        rows.append({
            "id": f"{system_slug}:rule:{rule_id}",
            "system_slug": system_slug,
            "source_sha256": source_hash,
            "name": candidate["name"].strip(),
            "category": candidate["category"],
            "summary": candidate["summary"].strip(),
            "page_pdf": page_number,
            "evidence_quote": quote.strip(),
            "source_priority": priority,
            "status": "needs_review",
        })
    report = {"received": len(candidates), "valid_provenance": len(rows), "issues": issues}
    if issues:
        return report
    destination = processed / "entities"
    write_jsonl(destination / "rules.jsonl", rows)
    write_json(destination / "rules_report.json", report)
    return report
