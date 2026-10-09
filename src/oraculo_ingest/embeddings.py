"""Embeddings locais; o livro nunca é enviado a um serviço remoto."""

from __future__ import annotations

import json
from pathlib import Path

from .pipeline import read_jsonl, write_json

DEFAULT_MODEL = "intfloat/multilingual-e5-small"


def embed(system_dir: Path, model_name: str = DEFAULT_MODEL) -> dict:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError('Instale as dependências com: pip install -e ".[embeddings]"') from exc

    output = system_dir / "processed"
    chunks = read_jsonl(output / "chunks.jsonl")
    if not chunks:
        raise ValueError("Nenhum chunk disponível para embeddings.")
    try:
        model = SentenceTransformer(model_name, local_files_only=True)
    except (OSError, ValueError):
        # Primeiro uso: baixar o modelo. Reprocessamentos usam o cache local.
        model = SentenceTransformer(model_name)
    vectors = model.encode(
        ["passage: " + chunk["text"] for chunk in chunks],
        batch_size=16,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    vectors = np.asarray(vectors, dtype=np.float32)
    np.save(output / "embeddings.npy", vectors)
    metadata = {
        "model": model_name,
        "prefix": "passage: ",
        "query_prefix": "query: ",
        "normalized": True,
        "chunk_ids": [chunk["id"] for chunk in chunks],
        "shape": list(vectors.shape),
    }
    write_json(output / "embeddings.json", metadata)
    return metadata
