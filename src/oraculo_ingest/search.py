"""Busca semântica local para revisar a qualidade dos chunks."""

from __future__ import annotations

import json
from pathlib import Path

from .pipeline import read_jsonl


def rank_chunks(chunks: list[dict], chunk_ids: list[str], vectors, query_vector, top: int) -> list[dict]:
    """Ordena chunks por similaridade de cosseno; vetores já normalizados."""
    import numpy as np

    if top < 1:
        raise ValueError("--top deve ser maior que zero.")
    if len(chunks) != len(chunk_ids) or len(chunks) != len(vectors):
        raise ValueError("Chunks e embeddings têm tamanhos diferentes. Gere os embeddings novamente.")
    if [chunk["id"] for chunk in chunks] != chunk_ids:
        raise ValueError("A ordem dos chunks mudou. Gere os embeddings novamente.")
    scores = np.asarray(vectors @ query_vector, dtype=float)
    order = np.argsort(scores)[::-1][:top]
    return [{**chunks[int(i)], "score": float(scores[i])} for i in order]


def search(system_dir: Path, question: str, top: int = 5) -> list[dict]:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError('Instale as dependências com: pip install -e ".[embeddings]"') from exc

    if not question.strip():
        raise ValueError("Digite uma pergunta para buscar.")
    output = system_dir / "processed"
    metadata = json.loads((output / "embeddings.json").read_text(encoding="utf-8"))
    chunks = read_jsonl(output / "chunks.jsonl")
    vectors = np.load(output / "embeddings.npy", mmap_mode="r", allow_pickle=False)
    if list(vectors.shape) != metadata["shape"]:
        raise ValueError("Formato dos embeddings diverge dos metadados.")
    try:
        model = SentenceTransformer(metadata["model"], local_files_only=True)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Modelo de embeddings não encontrado no cache local. Execute 'embed' "
            "no mesmo usuário do Windows antes de buscar."
        ) from exc
    query_vector = model.encode(
        metadata.get("query_prefix", "query: ") + question.strip(),
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return rank_chunks(chunks, metadata["chunk_ids"], vectors, query_vector, top)
