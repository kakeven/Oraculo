import sqlite3

import pytest

from oraculo_ingest.campaign_db import (SCHEMA, add_entity, add_npc, add_proposal, campaign_snapshot,
                                        connect, create_campaign, create_session,
                                        record_event, review_proposal)


def test_campaign_state_survives_reopen_and_migration_is_repeatable(tmp_path):
    path = tmp_path / "campaigns.sqlite3"
    with connect(path) as db:
        campaign = create_campaign(db, "Cidade Velada", "mutantes-malfeitores", "Heróis em crise")
        entity = add_entity(db, campaign, "character", "Vésper", attributes={"role": "rival"})
        session = create_session(db, campaign, 1, "O apagão")
        event = record_event(db, campaign, "decision", "O grupo salvou a estação.", "player",
                             session_id=session, entity_id=entity)
        proposal = add_proposal(db, campaign, "consequence", {"text": "A cidade reage"},
                                source_refs=[{"chunk_id": "abc", "page": 12}], model="example")
    with connect(path) as db:
        snapshot = campaign_snapshot(db, campaign)
        assert snapshot["campaign"]["premise"] == "Heróis em crise"
        assert snapshot["entities"][0]["attributes"] == {"role": "rival"}
        assert snapshot["sessions"][0]["id"] == session
        assert snapshot["events"][0]["id"] == event
        assert snapshot["pending_proposals"][0]["id"] == proposal
        review_proposal(db, proposal, True)
        assert campaign_snapshot(db, campaign)["pending_proposals"] == []
        assert db.execute("SELECT status FROM ai_proposals WHERE id = ?", (proposal,)).fetchone()[0] == "accepted"
        with pytest.raises(ValueError, match="já revisada"):
            review_proposal(db, proposal, False)
        assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_cross_campaign_references_are_rejected(tmp_path):
    with connect(tmp_path / "campaigns.sqlite3") as db:
        first = create_campaign(db, "Primeira", "mutantes-malfeitores")
        second = create_campaign(db, "Segunda", "mutantes-malfeitores")
        session = create_session(db, first, 1, "Abertura")
        entity = add_entity(db, first, "location", "Torre")
        with pytest.raises(sqlite3.IntegrityError):
            record_event(db, second, "scene", "Cena errada", "gm", session_id=session)
        with pytest.raises(sqlite3.IntegrityError):
            record_event(db, second, "scene", "Cena errada", "gm", entity_id=entity)
        assert campaign_snapshot(db, second)["events"] == []


def test_existing_v1_database_gains_npc_profiles(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as old_db:
        old_db.executescript(SCHEMA)
        old_db.execute("INSERT INTO schema_migrations(version) VALUES (1)")
    with connect(path) as db:
        campaign = create_campaign(db, "Cidade", "mutantes-malfeitores")
        npc = add_npc(db, campaign, "Vésper", {
            "traits": ["desconfiada", "leal"],
            "motivations": ["proteger a irmã"],
            "voice": "fala pouco",
            "secrets": ["conhece o vilão"],
        })
        entity = campaign_snapshot(db, campaign)["entities"][0]
        assert entity["id"] == npc
        assert entity["kind"] == "character"
        assert entity["npc_personality"]["motivations"] == ["proteger a irmã"]
        assert [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
