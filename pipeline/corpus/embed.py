"""Embeddings for the chunks, on Apple MPS when present.

Models (both MIT licence, checked on their Hugging Face model cards):
  bge   BAAI/bge-small-en-v1.5   384 dims, 33M params, query prefix
  e5    intfloat/e5-base-v2      768 dims, 110M params, "query: " and "passage: " prefixes

Vectors are L2-normalised and saved as float16: corpus/index/<model>.f16.npy, with
corpus/index/<model>.ids.json giving the chunk_id for each row. The text embedded is the
heading path plus the chunk text. Both models read at most 512 tokens, so the tail of a
long chunk is seen only by BM25.

Run:
    python -m pipeline.corpus.embed                       # both models, MPS
    python -m pipeline.corpus.embed --bench 512           # chunks/s on MPS and CPU, by batch size
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from typing import Any

import numpy as np

from pipeline.corpus.chunk import load_chunks
from pipeline.corpus.paths import set_model_cache, sub

MODELS = {
    "bge": {
        "name": "BAAI/bge-small-en-v1.5",
        "query": "Represent this sentence for searching relevant passages: ",
        "passage": "",
        "licence": "MIT",
    },
    "e5": {"name": "intfloat/e5-base-v2", "query": "query: ", "passage": "passage: ", "licence": "MIT"},
}
MAX_SEQ = 512


def device() -> str:
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


_LOADED: dict[tuple[str, str], Any] = {}


def load_model(key: str, dev: str | None = None) -> Any:
    set_model_cache()
    from sentence_transformers import SentenceTransformer

    dev = dev or device()
    if (key, dev) not in _LOADED:
        m = SentenceTransformer(MODELS[key]["name"], device=dev)
        m.max_seq_length = MAX_SEQ
        _LOADED[(key, dev)] = m
    return _LOADED[(key, dev)]


def passage_text(c: dict[str, Any], key: str) -> str:
    return MODELS[key]["passage"] + (c.get("heading_path") or "") + "\n" + c["text"]


def encode_passages(key: str, texts: list[str], batch: int = 32, dev: str | None = None) -> np.ndarray:
    m = load_model(key, dev)
    v = m.encode(texts, batch_size=batch, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    return v.astype(np.float16)


def encode_query(key: str, query: str) -> np.ndarray:
    m = load_model(key)
    v = m.encode([MODELS[key]["query"] + query], normalize_embeddings=True, convert_to_numpy=True)
    return v[0].astype(np.float32)


def build(keys: list[str], batch: int = 32) -> dict[str, Any]:
    chunks = load_chunks()
    out = sub("index")
    stats = {}
    for key in keys:
        ids_path = out / f"{key}.ids.json"
        vec_path = out / f"{key}.f16.npy"
        done: dict[str, int] = {}
        old = None
        keys_path = out / f"{key}.keys.json"
        if ids_path.exists() and vec_path.exists() and keys_path.exists():
            old = np.load(vec_path)
            done = {k: i for i, k in enumerate(json.loads(keys_path.read_text()))}
        # reuse a vector only when the embedded text is the same (key = hash of the text)
        ckey = {c["chunk_id"]: hashlib.sha1(passage_text(c, key).encode()).hexdigest() for c in chunks}
        todo = [c for c in chunks if ckey[c["chunk_id"]] not in done]
        t0 = time.time()
        new = encode_passages(key, [passage_text(c, key) for c in todo], batch) if todo else None
        dt = time.time() - t0
        vecs, ids = [], []
        new_i = {c["chunk_id"]: i for i, c in enumerate(todo)}
        dim = new.shape[1] if new is not None else old.shape[1]  # type: ignore[union-attr]
        for c in chunks:
            cid = c["chunk_id"]
            if cid in new_i:
                vecs.append(new[new_i[cid]])  # type: ignore[index]
            else:
                vecs.append(old[done[ckey[cid]]])  # type: ignore[index]
            ids.append(cid)
        arr = np.vstack(vecs).astype(np.float16) if vecs else np.zeros((0, dim), np.float16)
        np.save(vec_path, arr)
        ids_path.write_text(json.dumps(ids))
        keys_path.write_text(json.dumps([ckey[i] for i in ids]))
        stats[key] = {
            "chunks": len(ids),
            "new": len(todo),
            "seconds": round(dt, 1),
            "chunks_per_s": round(len(todo) / dt, 1) if todo and dt else None,
            "device": device(),
            "bytes": vec_path.stat().st_size,
        }
        print(key, stats[key], flush=True)
    (out / "embed_stats.json").write_text(json.dumps(stats, indent=1))
    return stats


def bench(n: int) -> list[dict[str, Any]]:
    import torch

    chunks = load_chunks()[:n]
    rows = []
    for key in MODELS:
        texts = [passage_text(c, key) for c in chunks]
        for dev in ["mps", "cpu"]:
            if dev == "mps" and not torch.backends.mps.is_available():
                continue
            for b in [8, 16, 32, 64] if dev == "mps" else [32]:
                encode_passages(key, texts[:16], b, dev)  # warm up
                if dev == "mps":
                    torch.mps.synchronize()
                t0 = time.time()
                encode_passages(key, texts, b, dev)
                if dev == "mps":
                    torch.mps.synchronize()
                dt = time.time() - t0
                mem = torch.mps.driver_allocated_memory() / 2**20 if dev == "mps" else None
                rows.append(
                    {
                        "model": key,
                        "device": dev,
                        "batch": b,
                        "chunks": len(texts),
                        "seconds": round(dt, 2),
                        "chunks_per_s": round(len(texts) / dt, 1),
                        "mps_driver_mb": round(mem) if mem else None,
                    }
                )
                print(rows[-1], flush=True)
    (sub("index") / "embed_bench.json").write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="bge,e5")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--bench", type=int, default=0)
    a = ap.parse_args()
    if a.bench:
        bench(a.bench)
    else:
        build(a.models.split(","), a.batch)
