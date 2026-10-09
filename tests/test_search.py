import numpy as np
import pytest

from oraculo_ingest.search import rank_chunks


def test_rank_chunks_returns_relevant_chunk_and_rejects_stale_embeddings():
    chunks = [
        {"id": "a", "chapter": "Poderes", "text": "voar"},
        {"id": "b", "chapter": "Combate", "text": "iniciativa"},
    ]
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
    query = np.array([0.1, 0.9])
    assert rank_chunks(chunks, ["a", "b"], vectors, query, 1)[0]["id"] == "b"
    with pytest.raises(ValueError, match="ordem dos chunks mudou"):
        rank_chunks(chunks, ["b", "a"], vectors, query, 1)
