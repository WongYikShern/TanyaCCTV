"""TEST-ONLY wrapper around tanya_bridge.py for keyless end-to-end tests. Never use in production.

Runs in the SentrySearch environment exactly like the real bridge, except that the Gemini query
embedding is replaced by the stored embedding of one indexed chunk, chosen with
E2E_QUERY_CHUNK="<filename>@<start_sec>" (e.g. "cam1_lobby.mp4@24"). Everything else is real:
argument parsing, the Chroma index, SentrySearch's search_footage, JSON output and redaction.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tanya_bridge  # noqa: E402


class _StoredChunkEmbedder:
    def __init__(self, vector):
        self.vector = vector

    def embed_query(self, text, verbose=False):
        return self.vector


def _install(argv):
    import sentrysearch.embedder as emb
    from sentrysearch.store import SentryStore

    name, start = os.environ["E2E_QUERY_CHUNK"].rsplit("@", 1)
    db = argv[argv.index("--db") + 1] if "--db" in argv else None
    got = SentryStore(db_path=db, backend="gemini").collection.get(include=["embeddings", "metadatas"])
    for meta, vec in zip(got["metadatas"], got["embeddings"]):
        if Path(meta["source_file"]).name == name and float(meta["start_time"]) == float(start):
            emb._current_embedder = _StoredChunkEmbedder(list(vec))
            return
    raise SystemExit(f"E2E_QUERY_CHUNK not found in index: {name}@{start}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "search":
        _install(argv)
    sys.exit(tanya_bridge.main(argv))
