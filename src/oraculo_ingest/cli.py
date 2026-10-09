"""Interface de linha de comando para a primeira etapa da ingestão."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .abilities import export_prompt, extract_abilities, import_result
from .embeddings import DEFAULT_MODEL, embed
from .openai_extractor import extract_with_openai
from .pipeline import prepare, rechunk
from .search import search
from .rules import import_rules
from .qa import ask_with_oraculo_login
from .catalog import find_entities, index_entities, load_entities
from .pipeline import choose_pdf, pdf_sha256
from collections import Counter

DEFAULT_DATA = Path.cwd() / "data" / "systems"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def main() -> None:
    parser = argparse.ArgumentParser(prog="oraculo")
    parser.add_argument(
        "command",
        choices=["prepare", "chunk", "embed", "search", "ask", "catalog-index", "catalog", "abilities-prompt", "abilities-import", "abilities-api", "rules-import"],
    )
    parser.add_argument("system", help="Slug da pasta do sistema, ex.: mutantes-malfeitores")
    parser.add_argument("question", nargs="?", help="Pergunta para o comando search")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Modelo local de embeddings")
    parser.add_argument("--top", type=int, default=5, help="Quantidade de resultados da busca")
    parser.add_argument("--category", choices=["ability", "skill", "advantage", "effect", "power_example", "modifier_extra", "modifier_flaw"],
                        help="Filtra os registros do catálogo")
    parser.add_argument("--input", type=Path, help="Resposta JSON para abilities-import")
    parser.add_argument("--llm-model", default="gpt-4o-mini", help="Modelo para abilities-api")
    parser.add_argument("--chatgpt-model", help="Modelo disponibilizado ao login do Oráculo para ask")
    parser.add_argument(
        "--allow-external-processing", action="store_true",
        help="Autoriza enviar conteúdo selecionado do livro ao serviço de IA",
    )
    args = parser.parse_args()
    if not SLUG_RE.fullmatch(args.system):
        parser.error("O sistema deve usar apenas letras minúsculas, números e hífens.")
    system_dir = args.data_dir / args.system
    try:
        if args.command == "prepare":
            result = prepare(system_dir)
        elif args.command == "chunk":
            result = rechunk(system_dir)
        elif args.command == "embed":
            result = embed(system_dir, args.model)
        elif args.command == "abilities-prompt":
            result = export_prompt(system_dir)
        elif args.command == "abilities-import":
            if args.input is None:
                parser.error("abilities-import exige --input com o caminho do JSON de resposta.")
            result = import_result(system_dir, args.input)
        elif args.command == "rules-import":
            if args.input is None:
                parser.error("rules-import exige --input com o caminho do JSON de regras.")
            result = import_rules(system_dir, args.input)
        elif args.command == "catalog-index":
            result = index_entities(system_dir)
        elif args.command == "catalog":
            source_hash = pdf_sha256(choose_pdf(system_dir / "source"))
            rows = load_entities(system_dir, source_hash)
            if args.question:
                result = [{"type": row["type"], "name": row["name"],
                           "pages": [row["page_start"], row["page_end"]], "id": row["id"]}
                          for row in find_entities(rows, args.question, args.top, args.category)]
            else:
                result = {"records": len(rows), "categories": dict(Counter(
                    row["type"] for row in rows if not args.category or row["type"] == args.category))}
        elif args.command == "ask":
            if args.question is None:
                parser.error("O comando ask precisa de uma pergunta entre aspas.")
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            print(ask_with_oraculo_login(system_dir, args.question, model=args.chatgpt_model,
                                         allow_external_processing=args.allow_external_processing))
            return
        elif args.command == "abilities-api":
            if not args.allow_external_processing:
                parser.error("abilities-api exige --allow-external-processing para enviar trechos à API.")
            result = extract_abilities(
                system_dir, lambda source: extract_with_openai(source, args.llm_model)
            )
        else:
            if args.question is None:
                parser.error("O comando search precisa de uma pergunta entre aspas.")
            matches = search(system_dir, args.question, args.top)
            for position, match in enumerate(matches, start=1):
                pages = str(match["page_start"])
                if match["page_end"] != match["page_start"]:
                    pages += f"-{match['page_end']}"
                preview = match["text"][:220].replace("\n", " ")
                print(f"{position}. {match['chapter']} | página(s) {pages} | similaridade {match['score']:.3f}")
                print(f"   {preview}...\n")
            return
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    if args.command == "embed":
        result = {"model": result["model"], "chunks": result["shape"][0], "dimensions": result["shape"][1]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
