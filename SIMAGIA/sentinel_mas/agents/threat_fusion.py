"""Zone-aware threat fusion.

Rules per zone are defined in THREAT_SCORES.md.

Belief flags consumed:
    cyber_anomaly     — a cyber log anomaly is active
    physical_presence — motion/PIR detected
    unknown_face      — a face was seen and did NOT match
    last_identity     — a face matched a known identity (authorized)
    motion_count      — number of motion events since last clear
"""

from config import settings

L = settings.THREAT_LOW
M = settings.THREAT_MEDIUM
H = settings.THREAT_HIGH
C = settings.THREAT_CRITICAL


def _flags(b):
    cyber      = bool(b.get("cyber_anomaly", False))
    physical   = bool(b.get("physical_presence", False))
    unknown    = bool(b.get("unknown_face", False))
    authorized = bool(b.get("last_identity")) and not unknown
    motion     = b.get("motion_count", 0)
    return cyber, physical, unknown, authorized, motion


def fuse(zone_id: str, b) -> tuple[int, str]:
    """Return (threat_level, interpretation) for a zone given its beliefs."""
    cyber, physical, unknown, authorized, motion = _flags(b)

    # ── Lobby / Exterior (zona pública — câmara + PIR) ───────────
    if zone_id in ("lobby", "exterior"):
        if physical:
            return M, "movimento detetado / pessoa presente"
        return L, "sem atividade"

    # ── Work Rooms (zona semi-restrita — câmara + PIR + cyber) ───
    if zone_id in ("work_room_1", "work_room_2", "work_room_3", "work_room_4"):
        unidentified = physical and not unknown and not authorized

        if cyber and physical and unknown:
            return C, "pessoa não autorizada + movimento + anomalia cibernética ativa"
        if cyber and unknown:
            return H, "face não reconhecida durante anomalia cibernética"
        if cyber and unidentified:
            return H, "presença não identificada durante anomalia cibernética"
        if cyber and authorized:
            return L, "funcionário autorizado presente"
        if cyber:
            return H, "estação de trabalho comprometida — ataque cibernético ativo"
        if physical and unknown:
            return H, "pessoa não autorizada + sensor de movimento"
        if physical and authorized:
            return L, "funcionário autorizado presente"
        if physical:
            return M, "movimento detetado — identidade desconhecida"
        return L, "sem atividade"

    # ── Server Room (zona crítica — câmara + PIR + cyber) ────────
    if zone_id == "server_room":
        unidentified = physical and not unknown and not authorized

        if physical and unknown:
            return C, "intruso confirmado no datacenter"
        if unidentified and cyber:
            return C, "presença não identificada + anomalia cibernética ativa no datacenter"
        if cyber and not physical:
            return H, "ataque remoto ativo — sem presença física"
        if unidentified:
            return H, "presença não identificada no datacenter — identidade por confirmar"
        if authorized and cyber:
            return M, "funcionário autorizado durante anomalia cibernética (possível insider)"
        if authorized:
            return M, "funcionário autorizado presente"
        return L, "sem atividade"

    # ── Fallback ──────────────────────────────────────────────────
    if cyber and unknown:
        return C, "anomalia cibernética + intruso"
    if cyber and not physical:
        return H, "anomalia remota"
    if unknown:
        return M, "presença não identificada"
    if cyber:
        return M, "anomalia cibernética"
    if physical:
        return M, "presença"
    return L, "sem atividade"
