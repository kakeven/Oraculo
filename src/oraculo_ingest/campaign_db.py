"""Estado local de campanhas. O livro continua na biblioteca de arquivos."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    system_slug TEXT NOT NULL,
    premise TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planning'
        CHECK(status IN ('planning', 'active', 'paused', 'completed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(id, system_slug)
);
CREATE TABLE IF NOT EXISTS campaign_entities (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('character', 'faction', 'location', 'item', 'lore', 'quest')),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    attributes_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes_json)),
    visibility TEXT NOT NULL DEFAULT 'gm' CHECK(visibility IN ('gm', 'players')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'resolved')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(campaign_id, id)
);
CREATE INDEX IF NOT EXISTS idx_entities_campaign_kind ON campaign_entities(campaign_id, kind);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    number INTEGER NOT NULL CHECK(number > 0),
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned', 'running', 'completed')),
    scheduled_at TEXT,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(campaign_id, id),
    UNIQUE(campaign_id, number)
);
CREATE TABLE IF NOT EXISTS campaign_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    session_id TEXT,
    entity_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('scene', 'decision', 'consequence', 'note', 'correction')),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    actor TEXT NOT NULL CHECK(actor IN ('gm', 'player', 'ai', 'system')),
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY(campaign_id, session_id) REFERENCES sessions(campaign_id, id),
    FOREIGN KEY(campaign_id, entity_id) REFERENCES campaign_entities(campaign_id, id)
);
CREATE INDEX IF NOT EXISTS idx_events_campaign_order ON campaign_events(campaign_id, id);
CREATE TABLE IF NOT EXISTS ai_proposals (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('campaign', 'entity', 'session', 'scene', 'consequence')),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    rationale TEXT NOT NULL DEFAULT '',
    source_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_refs_json)),
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_at TEXT,
    CHECK((status = 'pending' AND reviewed_at IS NULL) OR
          (status != 'pending' AND reviewed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_proposals_campaign_status ON ai_proposals(campaign_id, status);
"""

NPC_SCHEMA = """
CREATE TABLE IF NOT EXISTS npc_profiles (
    entity_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    profile_json TEXT NOT NULL CHECK(json_valid(profile_json) AND json_type(profile_json) = 'object'),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY(campaign_id, entity_id) REFERENCES campaign_entities(campaign_id, id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS npc_must_be_character
BEFORE INSERT ON npc_profiles
WHEN (SELECT kind FROM campaign_entities WHERE id = NEW.entity_id AND campaign_id = NEW.campaign_id) != 'character'
BEGIN
    SELECT RAISE(ABORT, 'NPC must reference a character');
END;
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open a database and apply the first migration, safely on repeated calls."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    try:
        db.executescript(
            "BEGIN IMMEDIATE;\n" + SCHEMA +
            "\nINSERT OR IGNORE INTO schema_migrations(version) VALUES (1);\nCOMMIT;"
        )
        db.executescript(
            "BEGIN IMMEDIATE;\n" + NPC_SCHEMA +
            "\nINSERT OR IGNORE INTO schema_migrations(version) VALUES (2);\nCOMMIT;"
        )
    except Exception:
        db.rollback()
        db.close()
        raise
    return db


def create_campaign(db: sqlite3.Connection, name: str, system_slug: str, premise: str = "") -> str:
    campaign_id = uuid4().hex
    with db:
        db.execute(
            "INSERT INTO campaigns(id, name, system_slug, premise) VALUES (?, ?, ?, ?)",
            (campaign_id, name.strip(), system_slug, premise),
        )
    return campaign_id


def add_entity(db: sqlite3.Connection, campaign_id: str, kind: str, name: str,
               description: str = "", attributes: dict | None = None,
               visibility: str = "gm") -> str:
    entity_id = uuid4().hex
    with db:
        db.execute(
            "INSERT INTO campaign_entities(id, campaign_id, kind, name, description, attributes_json, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entity_id, campaign_id, kind, name.strip(), description,
             json.dumps(attributes or {}, ensure_ascii=False), visibility),
        )
    return entity_id


def add_npc(db: sqlite3.Connection, campaign_id: str, name: str,
            personality: dict, description: str = "") -> str:
    """Create one campaign character and its GM-only personality profile atomically.

    The profile is flexible for different RPG systems. Suggested keys are traits,
    motivations, goals, voice, fears, and secrets; none is required yet.
    """
    if not isinstance(personality, dict):
        raise ValueError("A personalidade do NPC precisa ser um objeto JSON.")
    entity_id = uuid4().hex
    with db:
        db.execute(
            "INSERT INTO campaign_entities(id, campaign_id, kind, name, description, visibility) "
            "VALUES (?, ?, 'character', ?, ?, 'gm')",
            (entity_id, campaign_id, name.strip(), description),
        )
        db.execute(
            "INSERT INTO npc_profiles(entity_id, campaign_id, profile_json) VALUES (?, ?, ?)",
            (entity_id, campaign_id, json.dumps(personality, ensure_ascii=False)),
        )
    return entity_id


def create_session(db: sqlite3.Connection, campaign_id: str, number: int, title: str) -> str:
    session_id = uuid4().hex
    with db:
        db.execute(
            "INSERT INTO sessions(id, campaign_id, number, title) VALUES (?, ?, ?, ?)",
            (session_id, campaign_id, number, title.strip()),
        )
    return session_id


def record_event(db: sqlite3.Connection, campaign_id: str, kind: str, content: str,
                 actor: str, session_id: str | None = None,
                 entity_id: str | None = None) -> int:
    with db:
        cursor = db.execute(
            "INSERT INTO campaign_events(campaign_id, session_id, entity_id, kind, content, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, session_id, entity_id, kind, content.strip(), actor),
        )
    return cursor.lastrowid


def add_proposal(db: sqlite3.Connection, campaign_id: str, kind: str, content: dict,
                 rationale: str = "", source_refs: list | None = None,
                 model: str = "") -> str:
    proposal_id = uuid4().hex
    with db:
        db.execute(
            "INSERT INTO ai_proposals(id, campaign_id, kind, content_json, rationale, source_refs_json, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (proposal_id, campaign_id, kind, json.dumps(content, ensure_ascii=False),
             rationale, json.dumps(source_refs or [], ensure_ascii=False), model),
        )
    return proposal_id


def review_proposal(db: sqlite3.Connection, proposal_id: str, accept: bool) -> None:
    with db:
        result = db.execute(
            "UPDATE ai_proposals SET status = ?, reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE id = ? AND status = 'pending'",
            ("accepted" if accept else "rejected", proposal_id),
        )
        if result.rowcount != 1:
            raise ValueError("Proposta inexistente ou já revisada.")


def campaign_snapshot(db: sqlite3.Connection, campaign_id: str) -> dict:
    """Return durable state for a future generation/management agent."""
    campaign = db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if campaign is None:
        raise ValueError("Campanha não encontrada.")
    def rows(sql: str) -> list[dict]:
        return [dict(row) for row in db.execute(sql, (campaign_id,))]
    entities = rows("SELECT * FROM campaign_entities WHERE campaign_id = ? ORDER BY created_at, id")
    profiles = {
        row["entity_id"]: json.loads(row["profile_json"])
        for row in db.execute("SELECT entity_id, profile_json FROM npc_profiles WHERE campaign_id = ?", (campaign_id,))
    }
    for entity in entities:
        entity["attributes"] = json.loads(entity.pop("attributes_json"))
        if entity["id"] in profiles:
            entity["npc_personality"] = profiles[entity["id"]]
    return {
        "campaign": dict(campaign),
        "entities": entities,
        "sessions": rows("SELECT * FROM sessions WHERE campaign_id = ? ORDER BY number"),
        "events": rows("SELECT * FROM campaign_events WHERE campaign_id = ? ORDER BY id"),
        "pending_proposals": rows("SELECT * FROM ai_proposals WHERE campaign_id = ? AND status = 'pending' ORDER BY created_at, id"),
    }
