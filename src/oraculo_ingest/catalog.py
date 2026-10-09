"""Índice de seções nomeadas do livro, com posição e versão da fonte."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .catalog_layout import catalog_page_lines
from .pipeline import choose_pdf, pdf_sha256, read_jsonl, write_json, write_jsonl


SKILL_NAMES = {
    "Acrobacia", "Atletismo", "Combate à Distância", "Combate Corpo-a-Corpo",
    "Enganação", "Especialidade", "Furtividade", "Intimidação", "Intuição",
    "Investigação", "Percepção", "Persuasão", "Prestidigitação", "Tecnologia",
    "Tratamento", "Veículos",
}
ABILITY_RE = re.compile(r"^(.+?) \(([A-Z]{3})\)$")
ADVANTAGE_RE = re.compile(r"^(.+?) (COMBATE|PERÍCIA|SORTE|GERAL)(?:, GRADUAÇÕES(?: \([^)]*\))?)?$")
EFFECT_RE = re.compile(r"^(.+?) (ATAQUE|CONTROLE|DEFESA|GERAL|MOVIMENTO|SENSORIAL)$")
ABILITY_NAMES = {"força", "vigor", "agilidade", "destreza", "luta", "intelecto", "prontidão", "presença"}
ALIASES = {"voo": ["voar", "voando"], "dano": ["socar", "soco", "golpe"]}
STOP = {"para", "como", "quero", "fazer", "usar", "poder", "poderes", "efeito", "efeitos", "perícia", "perícias", "habilidade", "habilidades", "vantagem", "vantagens"}


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in text if not unicodedata.combining(character))


def words(value: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9]+", fold(value)) if len(term) >= 3 and term not in STOP]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(value)).strip("-")


def _heading(page: int, line: str, next_line: str) -> tuple[str, str, str] | None:
    title = line.strip()
    if page == 57:
        match = ABILITY_RE.fullmatch(title)
        if match and fold(match.group(1)) in {fold(name) for name in ABILITY_NAMES}:
            return "ability", match.group(1).title(), match.group(2)
    if 64 <= page <= 76 and fold(title) in {fold(name) for name in SKILL_NAMES}:
        return "skill", title.title(), ""
    if 78 <= page <= 88:
        match = ADVANTAGE_RE.fullmatch(title)
        if match and len(match.group(1)) >= 4 and not title.startswith("VANTAGENS "):
            return "advantage", match.group(1).title(), match.group(2).lower()
    if 95 <= page <= 129:
        match = EFFECT_RE.fullmatch(title)
        if match and len(match.group(1)) >= 3 and next_line.startswith("Ação:"):
            return "effect", match.group(1).title(), match.group(2).lower()
        if title == title.upper() and title and next_line.startswith("Efeito:"):
            return "power_example", title.title(), ""
    return None


def _visual_heading(page: int, line: dict[str, Any]) -> tuple[str, str, str] | None:
    title = line["heading"]
    size = line["heading_size"]
    if 64 <= page <= 76 and size == 24 and fold(line["text"]) in {fold(name) for name in SKILL_NAMES}:
        return "skill", line["text"].title(), ""
    if 78 <= page <= 88 and size == 14:
        match = ADVANTAGE_RE.fullmatch(title)
        if match:
            return "advantage", match.group(1).title(), match.group(2).lower()
    if 131 <= page <= 139 and size == 14 and title:
        return "modifier_extra", title.title(), ""
    if 140 <= page <= 146 and size == 14 and title:
        return "modifier_flaw", title.title(), ""
    return None


def _sections(pages: list[dict[str, Any]], source_hash: str, system_slug: str,
              visual: dict[int, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    groups = {"ability": (57, 57), "skill": (64, 76), "advantage": (78, 88),
              "power": (95, 129), "modifier_extra": (131, 139),
              "modifier_flaw": (140, 146)}
    rows: list[dict[str, Any]] = []
    for group, (first, last) in groups.items():
        lines = []
        for page in pages:
            number = page["page"]
            if not first <= number <= last:
                continue
            source_lines = (visual[number] if visual and number in visual
                            else [{"text": text, "heading": "", "heading_size": 0}
                                  for text in page["text"].splitlines()])
            if group == "advantage" and visual and number in visual:
                # Páginas 79–80: quadros de resumo, não descrições de vantagens.
                if number == 79:
                    first_item = next((i for i, item in enumerate(source_lines)
                                       if _visual_heading(number, item)), len(source_lines))
                    source_lines = source_lines[first_item:]
                elif number == 80:
                    source_lines = []
                elif number == 81:
                    banner = next((item["y"] for item in source_lines
                                   if "ARTES MARCIAIS E ESTILOS DE LUTA" in item["text"]), None)
                    if banner is not None:
                        source_lines = [item for item in source_lines if item["y"] > banner]
            lines.extend((number, index, item) for index, item in enumerate(source_lines)
                         if item["text"].strip() and
                         not (index < 2 and item["text"].strip().isdigit()))
        starts = []
        for position, (number, line_no, item) in enumerate(lines):
            next_line = lines[position + 1][2]["text"] if position + 1 < len(lines) else ""
            match = (_visual_heading(number, item) if visual and number in visual
                     else _heading(number, item["text"], next_line))
            if match and (group == "power" or match[0] == group):
                starts.append((position, match))
        for index, (start, (kind, name, subtype)) in enumerate(starts):
            end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
            excerpt = lines[start:end]
            if not excerpt:
                continue
            row_id = f"{system_slug}:{kind}:{_slug(name)}"
            rows.append({
                "id": row_id, "type": kind, "name": name, "subtype": subtype,
                "source_sha256": source_hash,
                "page_start": excerpt[0][0], "line_start": excerpt[0][1],
                "page_end": excerpt[-1][0], "line_end": excerpt[-1][1],
                "text": "\n".join(item["text"].strip() for _, _, item in excerpt),
                "status": "needs_review",
            })
    duplicates = [name for name, count in Counter(row["id"] for row in rows).items() if count > 1]
    if duplicates:
        raise ValueError(f"O índice contém nomes repetidos: {duplicates[:8]}.")
    return rows


def index_entities(system_dir: Path) -> dict[str, Any]:
    processed = system_dir / "processed"
    manifest = json.loads((processed / "manifest.json").read_text(encoding="utf-8"))
    source_hash = pdf_sha256(choose_pdf(system_dir / "source"))
    if manifest["source_sha256"] != source_hash:
        raise ValueError("O PDF mudou. Execute 'prepare' antes de indexar entidades.")
    pages = read_jsonl(processed / "pages.jsonl")
    visual = None
    try:
        reader = PdfReader(str(choose_pdf(system_dir / "source")), strict=False)
        selected = set(range(64, 89)) | set(range(131, 147))
        visual = catalog_page_lines(reader, selected)
    except PdfReadError:
        # Os testes de catálogo usam um PDF mínimo apenas para validar a proveniência.
        pass
    rows = _sections(pages, source_hash, system_dir.name, visual)
    destination = processed / "entities"
    write_jsonl(destination / "catalog.jsonl", rows)
    counts = dict(Counter(row["type"] for row in rows))
    report = {"source_sha256": source_hash, "counts": counts, "records": len(rows),
              "status": "needs_review"}
    write_json(destination / "catalog_report.json", report)
    return report


def load_entities(system_dir: Path, source_hash: str) -> list[dict[str, Any]]:
    path = system_dir / "processed" / "entities" / "catalog.jsonl"
    if not path.exists():
        return []
    rows = read_jsonl(path)
    if any(row.get("source_sha256") != source_hash for row in rows):
        raise ValueError("Índice de regras de outra versão do PDF. Execute 'catalog-index'.")
    return rows


def find_entities(rows: list[dict[str, Any]], question: str, top: int = 5,
                  kind: str | None = None) -> list[dict[str, Any]]:
    if top < 1:
        raise ValueError("--top deve ser maior que zero.")
    query = set(words(question))
    if not query:
        return []
    scored = []
    for row in rows:
        if kind and row["type"] != kind:
            continue
        name_words = set(words(row["name"]))
        aliases = set(words(" ".join(ALIASES.get(fold(row["name"]), []))))
        matched_name = {name for name in name_words if any(
            name == term or (len(name) >= 5 and len(term) >= 5 and name[:5] == term[:5])
            for term in query
        )}
        matched_alias = {alias for alias in aliases if alias in query}
        if not matched_alias and (not name_words or matched_name != name_words):
            continue
        score = len(matched_name) * 4 + len(matched_alias) * 4 + (8 if matched_name == name_words else 0)
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1]["page_start"], item[1]["name"]))
    return [row for _, row in scored[:top]]
