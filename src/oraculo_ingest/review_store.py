"""Decisões de revisão ligadas ao conteúdo exato de cada item extraído."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import load_entities
from .pipeline import choose_pdf, pdf_sha256, read_jsonl


DECISIONS = {"approved", "needs_review"}


def fingerprint(row: dict[str, Any]) -> str:
    value = {key: row[key] for key in ("id", "source_sha256", "page_start", "line_start",
                                      "page_end", "line_end", "text")}
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def review_path(system_dir: Path) -> Path:
    return system_dir / "processed" / "entities" / "catalog_reviews.jsonl"


def edit_path(system_dir: Path) -> Path:
    return system_dir / "processed" / "entities" / "catalog_edits.jsonl"


def _edits(system_dir: Path) -> dict[str, dict[str, Any]]:
    path = edit_path(system_dir)
    if not path.exists():
        return {}
    latest = {}
    for event in read_jsonl(path):
        if isinstance(event.get("id"), str) and isinstance(event.get("text"), str):
            latest[event["id"]] = event
    return latest


def current_rows(system_dir: Path, require_catalog: bool = True) -> list[dict[str, Any]]:
    source_hash = pdf_sha256(choose_pdf(system_dir / "source"))
    rows = load_entities(system_dir, source_hash)
    if not rows and require_catalog:
        raise ValueError("Catálogo vazio. Execute 'oraculo catalog-index' antes da revisão.")
    edits = _edits(system_dir)
    effective = []
    for raw in rows:
        row = dict(raw)
        edit = edits.get(row["id"])
        row["original_text"] = raw["text"]
        if edit and edit.get("original_fingerprint") == fingerprint(raw):
            row["text"] = edit["text"]
        row["edited"] = row["text"] != raw["text"]
        effective.append(row)
    return effective


def _append(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def set_text(system_dir: Path, row_id: str, text: str,
             expected_fingerprint: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
        raise ValueError("O texto deve ter entre 1 e 100.000 caracteres.")
    row = next((entry for entry in current_rows(system_dir) if entry["id"] == row_id), None)
    if row is None:
        raise KeyError("Item não encontrado no catálogo atual.")
    if expected_fingerprint != fingerprint(row):
        raise RuntimeError("O texto mudou. Recarregue o item antes de salvar.")
    raw = {**row, "text": row["original_text"]}
    event = {
        "id": row_id, "source_sha256": row["source_sha256"],
        "original_fingerprint": fingerprint(raw), "text": text,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    _append(edit_path(system_dir), event)
    updated = {**row, "text": text, "edited": text != row["original_text"]}
    if text != row["text"]:
        set_decision(system_dir, row_id, "needs_review", fingerprint(updated))
    return {**updated, "fingerprint": fingerprint(updated),
            "state": state(updated, decisions(system_dir))}


def decisions(system_dir: Path) -> dict[str, dict[str, Any]]:
    path = review_path(system_dir)
    if not path.exists():
        return {}
    latest = {}
    for event in read_jsonl(path):
        if event.get("decision") in DECISIONS:
            latest[event["id"]] = event
    return latest


def state(row: dict[str, Any], latest: dict[str, dict[str, Any]]) -> str:
    event = latest.get(row["id"])
    if event and event.get("fingerprint") == fingerprint(row):
        return event["decision"]
    return "needs_review"


def set_decision(system_dir: Path, row_id: str, decision: str,
                 expected_fingerprint: str) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError("Decisão inválida.")
    row = next((entry for entry in current_rows(system_dir) if entry["id"] == row_id), None)
    if row is None:
        raise KeyError("Item não encontrado no catálogo atual.")
    current_fingerprint = fingerprint(row)
    if expected_fingerprint != current_fingerprint:
        raise RuntimeError("O texto mudou. Recarregue o item antes de decidir.")
    event = {
        "id": row_id, "source_sha256": row["source_sha256"],
        "fingerprint": current_fingerprint, "decision": decision,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    _append(review_path(system_dir), event)
    return event
