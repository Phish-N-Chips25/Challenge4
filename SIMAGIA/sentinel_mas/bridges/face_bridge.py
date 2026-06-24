"""Bridge: the trained InsightFace face-recognition model → the MAS.

The FaceIDAgent reactive agent uses this to turn a captured frame into an
identity (a known person, or "unknown"), which then drives threat fusion
exactly like the old simulated face sensor — but for real. A recognised
intruder becomes the genuine trigger for threat escalation and patrol dispatch.

Soft-fallback (same discipline as nav_bridge): if the ML deps
(insightface / opencv-python / scikit-learn / onnxruntime) or the embeddings
DB aren't available, make_face_recognizer() returns None and the FaceIDAgent
keeps its simulated sensor — so the MAS runs either way.

The frame feed is abstracted behind FrameSource so it can move from the
synthetic faces/ pool (offline demo) to live Webots camera frames later with
NO change to the agent.
"""

from __future__ import annotations

import pickle
import random
import sys
from pathlib import Path
from typing import Optional

from config import settings


# ── Recognition ──────────────────────────────────────────────────────────────

class FaceRecognizer:
    """Wraps alt1.validar_pessoa_detalhes with a preloaded embeddings DB.

    recognize(image) → normalised dict:
        {"has_face": bool, "identity": str|None, "confidence": float,
         "authorized": bool}
    identity is the matched person's name when authorised, else "unknown".
    """

    def __init__(self, db, alt1_module):
        self._db = db
        self._alt1 = alt1_module
        self._model = None   # heavy InsightFace model, loaded on first use

    def recognize(self, image) -> dict:
        if self._model is None:
            self._model = self._alt1.obter_modelo()   # first call only
        res = self._alt1.validar_pessoa_detalhes(
            image, base_de_dados=self._db, app=self._model
        )
        reason = res.get("reason")
        if reason in ("sem_rosto", "imagem_invalida", "base_vazia"):
            return {"has_face": False, "identity": None,
                    "confidence": 0.0, "authorized": False}
        authorized = bool(res.get("allowed"))
        identity = res.get("matched_name") if authorized else "unknown"
        return {"has_face": True, "identity": identity or "unknown",
                "confidence": float(res.get("score") or 0.0),
                "authorized": authorized}


def make_face_recognizer() -> Optional[FaceRecognizer]:
    """Return a FaceRecognizer, or None to signal "use the simulated sensor"."""
    if not settings.USE_FACE_RECOGNITION:
        return None
    try:
        if settings.FACE_MODEL_DIR not in sys.path:
            sys.path.insert(0, settings.FACE_MODEL_DIR)
        import alt1   # noqa: E402 — imports insightface at top → ImportError if missing
        with open(settings.FACE_DB_PKL, "rb") as fh:
            payload = pickle.load(fh)
        db = payload.get("base_de_dados") if isinstance(payload, dict) else None
        if not db:
            raise ValueError("empty / invalid base_de_dados.pkl")
        return FaceRecognizer(db, alt1)
    except Exception as e:
        print(f"[face_bridge] face recognition unavailable ({e!r}); "
              f"FaceIDAgent will use the simulated sensor. "
              f"(pip install insightface opencv-python scikit-learn onnxruntime "
              f"to enable the real model.)")
        return None


# ── Frame sources (swap pool → camera later, no agent change) ────────────────

class FrameSource:
    """Where a face camera's frame for a given zone comes from."""

    def capture(self, zone: str):
        raise NotImplementedError


class PoolFrameSource(FrameSource):
    """Offline demo feed: a random still image from a folder pool. Replaceable
    by a live Webots-camera source with no FaceIDAgent change."""

    _EXT = (".jpg", ".jpeg", ".png", ".bmp")

    def __init__(self, pool_dir):
        self._pool = [str(p) for p in Path(pool_dir).glob("*")
                      if p.suffix.lower() in self._EXT]

    def capture(self, zone: str):
        return random.choice(self._pool) if self._pool else None


def make_frame_source() -> FrameSource:
    return PoolFrameSource(settings.FACE_POOL_DIR)
