"""Zone-aware threat fusion.

Mirrors the per-zone "Possible Interactions" of the design table: each zone
has its own sensor modalities and its own interpretation of the evidence.
`fuse()` returns (threat_level, interpretation) so the ZoneCoordinator can
both pick a plan (by level) and report *why* (the interpretation string).

Belief flags consumed:
    cyber_anomaly     — a cyber log anomaly is active
    physical_presence — motion/PIR (or any presence) detected
    unknown_face      — a face was seen and did NOT match (mismatch)
    last_identity     — a face matched a known identity (authorized)
    motion_count      — number of motion events since last clear (loitering)
"""

from config import settings

L = settings.THREAT_LOW
M = settings.THREAT_MEDIUM
H = settings.THREAT_HIGH
C = settings.THREAT_CRITICAL


def _flags(b):
    cyber = bool(b.get("cyber_anomaly", False))
    physical = bool(b.get("physical_presence", False))
    unknown = bool(b.get("unknown_face", False))
    authorized = bool(b.get("last_identity")) and not unknown
    motion = b.get("motion_count", 0)
    return cyber, physical, unknown, authorized, motion


def fuse(zone_id: str, b) -> tuple[int, str]:
    """Return (threat_level, interpretation) for a zone given its beliefs."""
    cyber, physical, unknown, authorized, motion = _flags(b)

    # ── Server Room (motion + camera + cyber) ────────────────
    if zone_id == "server_room":
        if cyber and physical and unknown:
            return C, "correlated critical incident (cyber + intruder)"
        if cyber and physical and not authorized:
            return C, "unidentified presence during cyber anomaly"
        if cyber and authorized:
            return L, "benign admin activity"
        if cyber:                                   # cyber, no physical cover
            return H, "remote attack (no physical presence)"
        if physical and unknown:
            return H, "physical intruder"
        if physical and authorized:
            return L, "authorized presence"
        if physical:
            return M, "unidentified presence"
        return L, "clear"

    # ── Lobby / Exterior (motion + camera, no cyber) ─────────
    if zone_id in ("lobby", "exterior"):
        if physical and unknown:
            return H, "visual intruder" if zone_id == "lobby" else "unknown approach"
        if physical and authorized:
            return L, "authorized presence"
        if physical:
            return M, "unidentified presence" if zone_id == "lobby" else "perimeter presence"
        return L, "clear"

    # ── Lab (motion + cyber, NO camera → cannot verify face) ──
    if zone_id == "lab":
        if cyber and physical:
            return H, "presence correlated with cyber anomaly (patrol for ID)"
        if cyber:
            return H, "compromised workstation"
        if physical:
            return M, "unidentified presence (no camera coverage)"
        return L, "clear"

    # ── Corridor (motion only) ───────────────────────────────
    if zone_id == "corridor":
        if motion >= 3:
            return M, "suspicious loitering"
        if physical:
            return L, "transit"
        return L, "clear"

    # ── Fallback for any unlisted zone ───────────────────────
    if cyber and unknown:
        return C, "cyber + intruder"
    if cyber and not physical:
        return H, "remote anomaly"
    if unknown:
        return M, "unidentified presence"
    if cyber:
        return M, "cyber anomaly"
    if physical:
        return M, "presence"
    return L, "clear"
