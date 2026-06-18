"""Reactive agents — stimulus→response, no deliberation.

MotionAgent, FaceIDAgent, CyberSentinelAgent : wrap perception adapters
and forward events (INFORM) to the relevant ZoneCoordinator.

StaffRequestAgent : forwards staff access requests.
AlertAgent        : terminal sink — notifies the human operator.

In standalone mode each perception agent runs a *simulated* sensor
behaviour so the whole MAS can be exercised without Webots/ROS2.
"""

import asyncio
import random

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.template import Template

from config import settings
from utils import build_msg, parse_body
from utils.messaging import INFORM, REQUEST
import dashboard_log


# ════════════════════════════════════════════════════════════
#  Base reactive agent
# ════════════════════════════════════════════════════════════

class ReactiveAgent(Agent):
    """Common base: condition→action rules, no internal state beyond
    what's needed to route events."""

    name_tag = "Reactive"

    def log(self, text: str):
        print(f"[{self.name_tag}] {text}")
        dashboard_log.push(self.name_tag, text)


# ════════════════════════════════════════════════════════════
#  MotionAgent
# ════════════════════════════════════════════════════════════

class SimulatedMotionSensor(PeriodicBehaviour):
    """Stand-in for the PIR/vision motion adapter."""

    async def run(self):
        if random.random() < 0.15:  # sporadic motion events
            zone = random.choice(settings.ZONES)
            msg = build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, {
                "event": "motion_detected", "zone": zone,
            })
            await self.send(msg)
            self.agent.log(f"motion in '{zone}' -> INFORM ZC")


class WebotsSensorBehaviour(CyclicBehaviour):
    """Drains the WebotsBridge sensor queue and forwards events to the
    appropriate ZoneCoordinator — active only when WEBOTS_ENABLED=True."""

    async def run(self):
        from bridges import get_bridge
        bridge = get_bridge()
        if bridge is None:
            await asyncio.sleep(0.1)
            return
        event = bridge.get_sensor_event(timeout=0.05)
        if event is None:
            return
        zone = event.get("zone")
        if zone not in settings.ZONES:
            return
        msg = build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, event)
        await self.send(msg)
        self.agent.log(f"{event.get('event')} in '{zone}' -> INFORM ZC")


class MotionAgent(ReactiveAgent):
    name_tag = "Motion"

    async def setup(self):
        self.log("starting (reactive)")
        if settings.WEBOTS_ENABLED:
            self.add_behaviour(WebotsSensorBehaviour())
        elif settings.SIMULATED_SENSORS:
            self.add_behaviour(SimulatedMotionSensor(period=4))


# ════════════════════════════════════════════════════════════
#  FaceIDAgent
# ════════════════════════════════════════════════════════════

class SimulatedFaceSensor(PeriodicBehaviour):
    """Stand-in for the YOLOv8 → InsightFace → liveness pipeline."""

    async def run(self):
        if random.random() < 0.12:
            zone = random.choice(settings.ZONES)
            identity = random.choice(["alice", "bob", "unknown", "unknown"])
            msg = build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, {
                "event": "face_detected",
                "zone": zone,
                "identity": identity,
                "confidence": round(random.uniform(0.7, 0.99), 2),
                "liveness": True,
            })
            await self.send(msg)
            self.agent.log(f"face '{identity}' in '{zone}' -> INFORM ZC")


class ReverifyHandler(CyclicBehaviour):
    """Respond to REQUEST reverify from a ZoneCoordinator.

    Webots mode: forwards the request to the bridge so the supervisor
    can relay it to the physical facecam; the camera's next scan will
    arrive automatically via WebotsSensorBehaviour.
    Simulation mode: returns a random identity as before.
    """

    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        body = parse_body(msg)
        if body.get("action") != "reverify":
            return
        zone = body.get("zone")

        if settings.WEBOTS_ENABLED:
            from bridges import get_bridge
            bridge = get_bridge()
            if bridge:
                bridge.put_patrol_command({"action": "reverify", "zone": zone})
            self.agent.log(f"reverify in '{zone}' -> relayed to Webots camera")
            return

        identity = random.choice(["alice", "bob", "carol", "unknown"])
        reply = build_msg(str(msg.sender), INFORM, {
            "event": "face_detected", "zone": zone,
            "identity": identity, "confidence": 0.95, "liveness": True,
            "reverification": True,
        })
        await self.send(reply)
        self.agent.log(f"reverify in '{zone}' -> '{identity}'")


class FaceIDAgent(ReactiveAgent):
    name_tag = "FaceID"

    async def setup(self):
        self.log("starting (reactive)")
        if not settings.WEBOTS_ENABLED and settings.SIMULATED_SENSORS:
            self.add_behaviour(SimulatedFaceSensor(period=5))
        t = Template()
        t.set_metadata("performative", REQUEST)
        self.add_behaviour(ReverifyHandler(), t)


# ════════════════════════════════════════════════════════════
#  CyberSentinelAgent
# ════════════════════════════════════════════════════════════

class SimulatedCyberSensor(PeriodicBehaviour):
    """Stand-in for DualSentinel (autoencoder + LLM on Sysmon logs)."""

    async def run(self):
        if random.random() < 0.10:
            zone = random.choice(["server_room", "lab"])  # cyber assets live here
            msg = build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, {
                "event": "cyber_anomaly",
                "zone": zone,
                "score": round(random.uniform(0.6, 0.99), 2),
                "source": "sysmon",
            })
            await self.send(msg)
            self.agent.log(f"anomaly in '{zone}' -> INFORM ZC")


class CyberSentinelAgent(ReactiveAgent):
    name_tag = "CyberSentinel"

    async def setup(self):
        self.log("starting (reactive)")
        if not settings.WEBOTS_ENABLED and settings.SIMULATED_SENSORS:
            self.add_behaviour(SimulatedCyberSensor(period=6))


# ════════════════════════════════════════════════════════════
#  StaffRequestAgent
# ════════════════════════════════════════════════════════════

class StaffRequestHandler(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        body = parse_body(msg)
        self.agent.log(f"staff request received: {body}")
        # Forward to the relevant ZC as an INFORM
        zone = body.get("zone", "lobby")
        fwd = build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, {
            "event": "staff_request", **body,
        })
        await self.send(fwd)


class StaffRequestAgent(ReactiveAgent):
    name_tag = "StaffRequest"

    async def setup(self):
        self.log("starting (reactive)")
        self.add_behaviour(StaffRequestHandler())


# ════════════════════════════════════════════════════════════
#  StressBurstAgent  (auction stress-test)
# ════════════════════════════════════════════════════════════

class StressBurstSensor(PeriodicBehaviour):
    """Fires crafted sensor events in ALL zones simultaneously.

    Strategy — **rotating CRITICAL slot**:
      Each burst promotes exactly ONE zone to CRITICAL threat while the
      remaining eligible zones land at HIGH.  The "CRITICAL zone" rotates
      every burst so that, across rounds, every zone gets a turn as the
      top bidder and auctions have genuine competition.

    Threat-level mapping (per threat_fusion rules):
      server_room CRITICAL → cyber + motion + unknown_face
      server_room HIGH     → cyber only  (remote attack, no physical)
      lobby/exterior HIGH  → motion + unknown_face
      lab HIGH             → cyber + motion
      corridor HIGH*       → motion_count ≥ 3  (needs multiple motion msgs)

    * corridor can only reach MEDIUM via threat_fusion, so it is skipped
      from the CRITICAL slot rotation (it would never bid at HIGH anyway).
    """

    # Zones that can reach HIGH or above — rotation candidates
    ROTATABLE = ["server_room", "lobby", "exterior",
                 "work_room_1", "work_room_2", "work_room_3", "work_room_4"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rotation_idx = 0          # which zone gets CRITICAL this round

    async def _send_critical(self, zone: str):
        """Emit events that push *zone* to CRITICAL (or its max reachable level)."""
        if zone == "server_room":
            # cyber + motion + unknown_face  →  CRITICAL (line 39 threat_fusion)
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "motion_detected", "zone": zone, "source": "stress_burst"},
            ))
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "cyber_anomaly", "zone": zone,
                 "score": round(random.uniform(0.85, 0.99), 2),
                 "source": "stress_burst"},
            ))
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "face_detected", "zone": zone,
                 "identity": "unknown",
                 "confidence": round(random.uniform(0.80, 0.99), 2),
                 "liveness": True, "source": "stress_burst"},
            ))

        elif zone in ("lobby", "exterior"):
            # motion + unknown_face  →  HIGH (visual intruder / unknown approach)
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "motion_detected", "zone": zone, "source": "stress_burst"},
            ))
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "face_detected", "zone": zone,
                 "identity": "unknown",
                 "confidence": round(random.uniform(0.80, 0.99), 2),
                 "liveness": True, "source": "stress_burst"},
            ))

        elif zone in ("work_room_1", "work_room_2", "work_room_3", "work_room_4"):
            # cyber + motion  →  HIGH (presence correlated with cyber anomaly)
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "motion_detected", "zone": zone, "source": "stress_burst"},
            ))
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "cyber_anomaly", "zone": zone,
                 "score": round(random.uniform(0.85, 0.99), 2),
                 "source": "stress_burst"},
            ))

    async def _send_high(self, zone: str):
        """Emit events that push *zone* to HIGH (but not CRITICAL)."""
        if zone == "server_room":
            # cyber only, no physical  →  HIGH "remote attack"
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "cyber_anomaly", "zone": zone,
                 "score": round(random.uniform(0.75, 0.90), 2),
                 "source": "stress_burst"},
            ))

        elif zone in ("lobby", "exterior"):
            # motion + unknown_face  →  HIGH
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "motion_detected", "zone": zone, "source": "stress_burst"},
            ))
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "face_detected", "zone": zone,
                 "identity": "unknown",
                 "confidence": round(random.uniform(0.75, 0.92), 2),
                 "liveness": True, "source": "stress_burst"},
            ))

        elif zone in ("work_room_1", "work_room_2", "work_room_3", "work_room_4"):
            # cyber + motion  →  HIGH
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "motion_detected", "zone": zone, "source": "stress_burst"},
            ))
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "cyber_anomaly", "zone": zone,
                 "score": round(random.uniform(0.65, 0.85), 2),
                 "source": "stress_burst"},
            ))

    async def run(self):
        critical_zone = self.ROTATABLE[self._rotation_idx % len(self.ROTATABLE)]
        self._rotation_idx += 1

        self.agent.log(
            f"=== STRESS BURST #{self._rotation_idx}: "
            f"CRITICAL slot → '{critical_zone}', "
            f"HIGH → {[z for z in self.ROTATABLE if z != critical_zone]} ==="
        )

        # ── 0. Reset sensor beliefs in all rotatable zones so stale physical_presence /
        #       unknown_face from previous rounds don't bleed into the new profile.
        #       We use "belief_reset" (NOT patrol_report/clear) to avoid flipping
        #       patrol_status from "en_route" to "clear" mid-mission.
        for zone in self.ROTATABLE:
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "belief_reset", "zone": zone, "source": "stress_burst"},
            ))
        # Give the ZoneCoordinators a moment to process the reset before the burst
        await asyncio.sleep(0.5)

        # ── 1. Fire the crafted threat profile
        await self._send_critical(critical_zone)

        for zone in self.ROTATABLE:
            if zone != critical_zone:
                await self._send_high(zone)

        self.agent.log("=== STRESS BURST complete ===")


class StressBurstAgent(ReactiveAgent):
    """Dedicated agent that owns the StressBurstSensor behaviour.

    Kept separate from the other reactive agents so it can be toggled
    independently via settings.AUCTION_STRESS_TEST without touching their
    individual simulation rates.
    """
    name_tag = "StressBurst"

    async def setup(self):
        self.log(
            f"starting (stress-test mode) — burst every "
            f"{settings.STRESS_BURST_INTERVAL}s"
        )
        self.add_behaviour(
            StressBurstSensor(period=settings.STRESS_BURST_INTERVAL)
        )


# ════════════════════════════════════════════════════════════
#  AlertAgent
# ════════════════════════════════════════════════════════════

class AlertSink(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        body = parse_body(msg)
        if body.get("event") == "alert":
            print("\n" + "=" * 60)
            print(f"  *** ALERT *** zone '{body.get('zone')}' "
                  f"threat={body.get('threat_level')}")
            print(f"  details: {body.get('details')}")
            print("=" * 60 + "\n")
            dashboard_log.push("ALERT", f"zone '{body.get('zone')}' "
                               f"threat={body.get('threat_level')} "
                               f"({body.get('details', {}).get('interpretation', '')})")


class AlertAgent(ReactiveAgent):
    name_tag = "Alert"

    async def setup(self):
        self.log("starting (reactive)")
        self.add_behaviour(AlertSink())
