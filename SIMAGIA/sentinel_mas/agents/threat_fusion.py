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
    """Return (threat_level, interpretation) for a zone given its beliefs.

    Zone-agnostic: the rules key off the zone's *capabilities* (which sensor
    modalities it has) rather than its name, so adding/renaming zones only
    needs a settings.ZONE_MODALITIES entry — no edits here. The four capability
    profiles correspond to the original design's four zone archetypes."""
    cyber, physical, unknown, authorized, motion = _flags(b)
    mods = settings.ZONE_MODALITIES.get(zone_id, {"motion"})
    has_camera = "camera" in mods
    has_cyber  = "cyber" in mods

    # ── Cyber + camera (e.g. datacenter) → richest, can reach CRITICAL ──
    if has_cyber and has_camera:
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

    # ── Cyber, NO camera (e.g. work rooms) → cannot verify a face ──
    if has_cyber:
        if cyber and physical:
            return H, "presence correlated with cyber anomaly (patrol for ID)"
        if cyber:
            return H, "compromised workstation"
        if physical:
            return M, "unidentified presence (no camera coverage)"
        return L, "clear"

    # ── Camera, no cyber (e.g. lobby / break_room) → visual ID, no cyber ──
    if has_camera:
        if physical and unknown:
            return H, "visual intruder"
        if physical and authorized:
            return L, "authorized presence"
        if physical:
            return M, "unidentified presence"
        return L, "clear"

    # ── Motion only (e.g. corridor) → transit, loitering at best MEDIUM ──
    if motion >= 3:
        return M, "suspicious loitering"
    if physical:
        return L, "transit"
    return L, "clear"
