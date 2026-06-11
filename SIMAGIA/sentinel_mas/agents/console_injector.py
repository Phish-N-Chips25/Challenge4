"""ConsoleInjectorAgent — in-process manual event injector.

Runs INSIDE the MAS process (same SPADE container as the coordinators), so
messages are routed in-memory — no second XMPP client, no network handshake.

Two ways to inject:
  * single events (1-6)  — one INFORM to a zone
  * scenarios   (a-e)    — a *burst* of several INFORMs to the same zone,
                           delivered back-to-back so the ZoneCoordinator's
                           threat-fusion sees them correlated in the same
                           deliberation window (this is how you exercise the
                           multi-modality interactions in the design table).

Enabled by launching:  python main.py --interactive
"""

import asyncio

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour

from config import settings
from utils import build_msg
from utils.messaging import INFORM


# Single events --------------------------------------------------------------
EVENTS: dict[str, dict] = {
    "1": {
        "label": "motion_detected          (physical presence)",
        "event": "motion_detected",
        "extra": {},
    },
    "2": {
        "label": "face_detected  unknown   (face mismatch -> unknown_face)",
        "event": "face_detected",
        "extra": {"identity": "unknown", "confidence": 0.95, "liveness": True},
    },
    "3": {
        "label": "face_detected  known     (face match alice -> authorized)",
        "event": "face_detected",
        "extra": {"identity": "alice", "confidence": 0.97, "liveness": True},
    },
    "4": {
        "label": "cyber_anomaly  HIGH      (score 0.92)",
        "event": "cyber_anomaly",
        "extra": {"score": 0.92, "source": "sysmon"},
    },
    "5": {
        "label": "cyber_anomaly  CRITICAL  (score 0.98)",
        "event": "cyber_anomaly",
        "extra": {"score": 0.98, "source": "sysmon"},
    },
    "6": {
        "label": "patrol_report  clear     (zone cleared - de-escalates)",
        "event": "patrol_report",
        "extra": {"status": "clear"},
    },
}

# Scenarios = bursts of single-event keys, sent together to one zone ----------
# (mirror the "Possible Interactions" column of the design table)
SCENARIOS: dict[str, dict] = {
    "a": {
        "label": "motion + face mismatch         -> intruder (visual/unknown approach)",
        "events": ["1", "2"],
    },
    "b": {
        "label": "cyber + motion, no face        -> presence during anomaly (max @ server)",
        "events": ["4", "1"],
    },
    "c": {
        "label": "cyber + motion + face mismatch -> correlated critical incident",
        "events": ["4", "1", "2"],
    },
    "d": {
        "label": "cyber + authorized face        -> benign admin activity",
        "events": ["4", "3"],
    },
    "e": {
        "label": "cyber alone (no presence)      -> remote attack / compromised host",
        "events": ["4"],
    },
}
# ----------------------------------------------------------------------------


# Which sensor modality each event represents (for zone-coverage warnings)
EVENT_MODALITY = {
    "motion_detected": "motion",
    "face_detected": "camera",
    "cyber_anomaly": "cyber",
    "patrol_report": None,        # control message, not a sensor
}


def _read(prompt: str) -> str:
    return input(prompt).strip()


def _menu() -> str:
    lines = ["\n" + "=" * 62, "  Event Injector"]
    lines.append("  -- single events --")
    for k, e in EVENTS.items():
        lines.append(f"  [{k}] {e['label']}")
    lines.append("  -- scenarios (burst of correlated events) --")
    for k, s in SCENARIOS.items():
        lines.append(f"  [{k}] {s['label']}")
    lines.append(f"  zones: {' / '.join(settings.ZONES)}")
    lines.append("  [q] quit")
    lines.append("=" * 62)
    return "\n".join(lines)


class ConsoleMenu(CyclicBehaviour):
    """Reads events/scenarios from stdin and sends them to a ZoneCoordinator."""

    async def _send_event(self, key: str, zone: str):
        ev = EVENTS[key]
        # Warn if the zone has no sensor for this modality (per design table)
        modality = EVENT_MODALITY.get(ev["event"])
        available = settings.ZONE_MODALITIES.get(zone, set())
        warn = ""
        if modality and modality not in available:
            warn = f"  (!) '{zone}' has no {modality} sensor"
        body = {"event": ev["event"], "zone": zone, **ev["extra"]}
        await self.send(build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, body))
        print(f"     -> [{ev['event']}] ZC:{zone}  {ev['extra'] or ''}{warn}")

    async def run(self):
        loop = asyncio.get_event_loop()
        zones = settings.ZONES
        print(_menu())

        try:
            choice = await loop.run_in_executor(None, _read, "  choice > ")
        except (EOFError, KeyboardInterrupt):
            await self.agent.stop()
            return

        choice = choice.lower()
        if choice == "q":
            print("  stopping...")
            await self.agent.stop()
            return

        is_event = choice in EVENTS
        is_scenario = choice in SCENARIOS
        if not (is_event or is_scenario):
            print("  invalid choice")
            return

        try:
            zone = await loop.run_in_executor(None, _read, "  zone   > ")
        except (EOFError, KeyboardInterrupt):
            await self.agent.stop()
            return

        if zone not in zones:
            print(f"  unknown zone (use: {', '.join(zones)})")
            return

        if is_event:
            await self._send_event(choice, zone)
        else:
            keys = SCENARIOS[choice]["events"]
            print(f"  >> scenario [{choice}] burst of {len(keys)} events -> {zone}")
            for k in keys:
                await self._send_event(k, zone)
                await asyncio.sleep(0.05)   # keep order, stay within one cycle
        print()
        await asyncio.sleep(0.3)


class ConsoleInjectorAgent(Agent):
    """A no-sensor agent whose only job is to relay manual console events."""

    async def setup(self):
        print("[Injector] interactive console ready")
        self.add_behaviour(ConsoleMenu())
