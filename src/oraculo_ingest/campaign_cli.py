"""CLI local para o primeiro ciclo de dados de campanha."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .campaign_db import (add_entity, add_npc, add_proposal, campaign_snapshot, connect,
                          create_campaign, create_session, record_event, review_proposal)


def main() -> None:
    parser = argparse.ArgumentParser(prog="oraculo-campaign")
    parser.add_argument("--db", type=Path, default=Path("data/campaigns/oraculo.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    create = commands.add_parser("create")
    create.add_argument("name")
    create.add_argument("system_slug")
    create.add_argument("--premise", default="")
    entity = commands.add_parser("entity")
    entity.add_argument("campaign_id")
    entity.add_argument("kind", choices=["character", "faction", "location", "item", "lore", "quest"])
    entity.add_argument("name")
    entity.add_argument("--description", default="")
    entity.add_argument("--visibility", choices=["gm", "players"], default="gm")
    npc = commands.add_parser("npc")
    npc.add_argument("campaign_id")
    npc.add_argument("name")
    npc.add_argument("profile_file", type=Path, help="Objeto JSON com a personalidade do NPC")
    npc.add_argument("--description", default="")
    session = commands.add_parser("session")
    session.add_argument("campaign_id")
    session.add_argument("number", type=int)
    session.add_argument("title")
    event = commands.add_parser("event")
    event.add_argument("campaign_id")
    event.add_argument("kind", choices=["scene", "decision", "consequence", "note", "correction"])
    event.add_argument("content")
    event.add_argument("--actor", choices=["gm", "player", "ai", "system"], default="gm")
    event.add_argument("--session-id")
    event.add_argument("--entity-id")
    show = commands.add_parser("show")
    show.add_argument("campaign_id")
    proposal = commands.add_parser("proposal")
    proposal.add_argument("campaign_id")
    proposal.add_argument("kind", choices=["campaign", "entity", "session", "scene", "consequence"])
    proposal.add_argument("json_file", type=Path)
    proposal.add_argument("--model", default="")
    review = commands.add_parser("review")
    review.add_argument("proposal_id")
    review.add_argument("decision", choices=["accept", "reject"])
    args = parser.parse_args()
    try:
        with connect(args.db) as db:
            if args.command == "init":
                result = {"database": str(args.db), "schema_version": 2}
            elif args.command == "create":
                result = {"campaign_id": create_campaign(db, args.name, args.system_slug, args.premise)}
            elif args.command == "entity":
                result = {"entity_id": add_entity(db, args.campaign_id, args.kind, args.name,
                                                   args.description, visibility=args.visibility)}
            elif args.command == "npc":
                profile = json.loads(args.profile_file.read_text(encoding="utf-8"))
                result = {"npc_id": add_npc(db, args.campaign_id, args.name, profile,
                                            args.description)}
            elif args.command == "session":
                result = {"session_id": create_session(db, args.campaign_id, args.number, args.title)}
            elif args.command == "event":
                result = {"event_id": record_event(db, args.campaign_id, args.kind, args.content,
                                                   args.actor, args.session_id, args.entity_id)}
            elif args.command == "show":
                result = campaign_snapshot(db, args.campaign_id)
            elif args.command == "proposal":
                content = json.loads(args.json_file.read_text(encoding="utf-8"))
                if not isinstance(content, dict):
                    raise ValueError("A proposta precisa ser um objeto JSON.")
                result = {"proposal_id": add_proposal(db, args.campaign_id, args.kind, content,
                                                      model=args.model)}
            else:
                review_proposal(db, args.proposal_id, args.decision == "accept")
                result = {"proposal_id": args.proposal_id, "status": "accepted" if args.decision == "accept" else "rejected"}
    except (sqlite3.Error, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
