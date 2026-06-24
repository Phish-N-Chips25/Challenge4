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
from bridges.face_bridge import make_face_recognizer, make_frame_source
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


class MotionAgent(ReactiveAgent):
    name_tag = "Motion"

    async def setup(self):
        self.log("starting (reactive)")
        if settings.SIMULATED_SENSORS:
            self.add_behaviour(SimulatedMotionSensor(period=4))


# ════════════════════════════════════════════════════════════
#  FaceIDAgent
# ════════════════════════════════════════════════════════════

class SimulatedFaceSensor(PeriodicBehaviour):
    """Stand-in for the YOLOv8 → InsightFace → liveness pipeline."""

    async def run(self):
        if random.random() < 0.12:
            camera_zones = settings.zones_with("camera")   # a face needs a camera
            if not camera_zones:
                return
            zone = random.choice(camera_zones)
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


class RealFaceSensor(PeriodicBehaviour):
    """Real perception: 'sees' a frame in a camera-equipped zone, runs the
    trained InsightFace model, and reports the identity to that zone's
    coordinator — same INFORM contract as SimulatedFaceSensor, real results.
    A recognised intruder ('unknown') is the genuine threat trigger.

    Inference runs in a thread executor so it never blocks the SPADE loop.
    The frame source is injected, so swapping the faces/ pool for live Webots
    camera frames later needs no change here."""

    def __init__(self, recognizer, source, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rec = recognizer
        self._src = source

    async def run(self):
        camera_zones = settings.zones_with("camera")
        if not camera_zones:
            return
        zone = random.choice(camera_zones)
        frame = self._src.capture(zone)
        if frame is None:
            return
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._rec.recognize, frame)
        if not result["has_face"]:
            return
        identity = result["identity"]
        await self.send(build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, {
            "event": "face_detected",
            "zone": zone,
            "identity": identity,
            "confidence": round(result["confidence"], 2),
            "liveness": True,
        }))
        tag = "authorized" if result["authorized"] else "UNKNOWN"
        self.agent.log(f"FaceID '{identity}' [{tag}] in '{zone}' "
                       f"(score={result['confidence']:.2f}) -> INFORM ZC")


class ReverifyHandler(CyclicBehaviour):
    """Respond to REQUEST reverify from a ZoneCoordinator."""

    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        body = parse_body(msg)
        if body.get("action") != "reverify":
            return
        zone = body.get("zone")
        # Simulated second capture — slightly biased toward resolution
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
        # Prefer the REAL trained model; fall back to the simulated sensor only
        # if it can't load (missing ML deps / DB) and simulated sensors are on.
        recognizer = make_face_recognizer()
        if recognizer is not None:
            self.add_behaviour(RealFaceSensor(recognizer, make_frame_source(), period=5))
            self.log("REAL InsightFace recognition active (faces/ pool, camera zones)")
        elif settings.SIMULATED_SENSORS:
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
            cyber_zones = settings.zones_with("cyber")   # zones with cyber assets
            if not cyber_zones:
                return
            zone = random.choice(cyber_zones)
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
        if settings.SIMULATED_SENSORS:
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

    Threat-level mapping (per threat_fusion rules, keyed on zone CAPABILITY):
      cyber+camera CRITICAL → cyber + motion + unknown_face
      cyber+camera HIGH     → cyber only  (remote attack, no physical)
      camera-only  HIGH     → motion + unknown_face
      cyber-only   HIGH     → cyber + motion
      motion-only  HIGH*    → motion_count ≥ 3  (needs multiple motion msgs)

    * motion-only zones can only reach MEDIUM via threat_fusion, so they are
      skipped from the rotation (they would never bid at HIGH anyway).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rotation_idx = 0          # which zone gets CRITICAL this round
        # Rotation candidates: any zone that can reach HIGH+ — i.e. has camera
        # OR cyber. Derived from modalities, so it tracks settings, not names.
        self.rotatable = [z for z in settings.ZONES
                          if {"camera", "cyber"} & settings.ZONE_MODALITIES.get(z, set())]

    async def _emit(self, zone: str, event: dict):
        event = {**event, "zone": zone, "source": "stress_burst"}
        await self.send(build_msg(settings.ZONE_COORDINATOR_JIDS[zone], INFORM, event))

    async def _motion(self, zone):
        await self._emit(zone, {"event": "motion_detected"})

    async def _cyber(self, zone, lo, hi):
        await self._emit(zone, {"event": "cyber_anomaly",
                                "score": round(random.uniform(lo, hi), 2)})

    async def _unknown_face(self, zone, lo, hi):
        await self._emit(zone, {"event": "face_detected", "identity": "unknown",
                                "confidence": round(random.uniform(lo, hi), 2),
                                "liveness": True})

    async def _send_critical(self, zone: str):
        """Emit events that push *zone* to CRITICAL (or its max reachable level),
        based on which sensor modalities the zone has."""
        mods = settings.ZONE_MODALITIES.get(zone, set())
        has_camera, has_cyber = "camera" in mods, "cyber" in mods
        if has_cyber and has_camera:
            # cyber + motion + unknown_face  →  CRITICAL
            await self._motion(zone)
            await self._cyber(zone, 0.85, 0.99)
            await self._unknown_face(zone, 0.80, 0.99)
        elif has_camera:
            # motion + unknown_face  →  HIGH (visual intruder)
            await self._motion(zone)
            await self._unknown_face(zone, 0.80, 0.99)
        elif has_cyber:
            # cyber + motion  →  HIGH (presence correlated with cyber anomaly)
            await self._motion(zone)
            await self._cyber(zone, 0.85, 0.99)

    async def _send_high(self, zone: str):
        """Emit events that push *zone* to HIGH (but not CRITICAL)."""
        mods = settings.ZONE_MODALITIES.get(zone, set())
        has_camera, has_cyber = "camera" in mods, "cyber" in mods
        if has_cyber and has_camera:
            # cyber only, no physical  →  HIGH "remote attack"
            await self._cyber(zone, 0.75, 0.90)
        elif has_camera:
            # motion + unknown_face  →  HIGH
            await self._motion(zone)
            await self._unknown_face(zone, 0.75, 0.92)
        elif has_cyber:
            # cyber + motion  →  HIGH
            await self._motion(zone)
            await self._cyber(zone, 0.65, 0.85)

    async def run(self):
        if not self.rotatable:
            return
        critical_zone = self.rotatable[self._rotation_idx % len(self.rotatable)]
        self._rotation_idx += 1

        self.agent.log(
            f"=== STRESS BURST #{self._rotation_idx}: "
            f"CRITICAL slot → '{critical_zone}', "
            f"HIGH → {[z for z in self.rotatable if z != critical_zone]} ==="
        )

        # ── 0. Reset sensor beliefs in all rotatable zones so stale physical_presence /
        #       unknown_face from previous rounds don't bleed into the new profile.
        #       We use "belief_reset" (NOT patrol_report/clear) to avoid flipping
        #       patrol_status from "en_route" to "clear" mid-mission.
        for zone in self.rotatable:
            await self.send(build_msg(
                settings.ZONE_COORDINATOR_JIDS[zone], INFORM,
                {"event": "belief_reset", "zone": zone, "source": "stress_burst"},
            ))
        # Give the ZoneCoordinators a moment to process the reset before the burst
        await asyncio.sleep(0.5)

        # ── 1. Fire the crafted threat profile
        await self._send_critical(critical_zone)

        for zone in self.rotatable:
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
