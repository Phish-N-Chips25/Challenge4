"""ZoneCoordinatorAgent — deliberative BDI agent (one per zone).

The only genuine BDI agents in SentinelMAS (per Wooldridge taxonomy).
Executes the full BDI cycle: belief revision ->desire generation →
plan selection (utility-weighted) ->intention execution.

ML stays in the perception layer; plan selection here is purely
logical conditions + utility weights.
"""

import time

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.template import Template

from config import settings
from utils import BeliefBase, Plan, PlanLibrary, generate_desires, build_msg, parse_body
from utils.messaging import (
    INFORM, REQUEST, CFP, PROPOSE, ACCEPT_PROPOSAL, REJECT_PROPOSAL,
)
from .threat_fusion import fuse
import dashboard_log

# Deliberation waits this long after the last perception before acting, so a
# burst of correlated events (e.g. cyber + motion + face) is fused atomically
# instead of reacting to each event separately.
SETTLE_SECONDS = 0.4


# ════════════════════════════════════════════════════════════
#  Behaviours
# ════════════════════════════════════════════════════════════

class PerceptionListener(CyclicBehaviour):
    """Belief revision: ingest INFORM messages from reactive agents
    and sensor adapters, updating the belief base."""

    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return

        body = parse_body(msg)
        event = body.get("event")

        if event == "face_detected":
            if body.get("identity") == "unknown":
                self.agent.beliefs.update("unknown_face", True)
                self.agent.beliefs.update("physical_presence", True)
            else:
                self.agent.beliefs.update("physical_presence", True)
                self.agent.beliefs.update("last_identity", body.get("identity"))
                # Identity resolved ->withdraw the unknown_face belief
                self.agent.beliefs.remove("unknown_face")

        elif event == "motion_detected":
            self.agent.beliefs.update("physical_presence", True)
            # Track repeated motion (used for corridor "loitering" detection)
            self.agent.beliefs.update(
                "motion_count", self.agent.beliefs.get("motion_count", 0) + 1
            )

        elif event == "cyber_anomaly":
            self.agent.beliefs.update("cyber_anomaly", True)
            self.agent.beliefs.update("anomaly_score", body.get("score", 0.0))

        elif event == "patrol_report":
            self.agent.beliefs.update("patrol_status", body.get("status"))
            if body.get("status") == "clear":
                # Patrol confirmed zone is clear ->reset to baseline
                self.agent.beliefs.update("threat_level", settings.THREAT_LOW)
                self.agent.beliefs.remove("cyber_anomaly")
                self.agent.beliefs.remove("unknown_face")
                self.agent.beliefs.remove("physical_presence")
                self.agent.beliefs.remove("alerted_level")
                self.agent.beliefs.update("motion_count", 0)

        elif event == "belief_reset":
            # Stress-test hook: clears sensor beliefs WITHOUT touching patrol_status.
            # Using patrol_report(clear) would flip patrol_status from
            # "en_route" to "clear", making the zone bid again mid-mission.
            self.agent.beliefs.remove("cyber_anomaly")
            self.agent.beliefs.remove("unknown_face")
            self.agent.beliefs.remove("physical_presence")
            self.agent.beliefs.remove("alerted_level")
            self.agent.beliefs.update("motion_count", 0)
            self.agent.beliefs.update("threat_level", settings.THREAT_LOW)

        # Mark the moment so deliberation can wait for a burst to settle
        self.agent.last_perception = time.time()
        self.agent.log(f"belief revision <-{event} | beliefs={self.agent.beliefs.snapshot()}")


class CFPResponder(CyclicBehaviour):
    """Contract Net bidder: reply to the PatrolAgent's CFP with a PROPOSE
    whose bid is this zone's current threat level (only if we still want
    patrol)."""

    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        if parse_body(msg).get("action") != "patrol_auction":
            return

        beliefs = self.agent.beliefs
        threat = beliefs.get("threat_level", 0)
        wants = threat >= settings.THREAT_HIGH and beliefs.get("patrol_status") != "en_route"
        if not wants:
            return                                  # not interested -> stay silent

        await self.send(build_msg(
            str(msg.sender), PROPOSE,
            {
                "zone": self.agent.zone_id,
                "bid": threat,
                "score": beliefs.get("anomaly_score", 0.0),
                "interpretation": beliefs.get("interpretation"),
            },
            thread=msg.thread,
        ))
        self.agent.log(f"PROPOSE bid={threat} for patrol (auction {msg.thread})")


class AuctionResultHandler(CyclicBehaviour):
    """Handle the auctioneer's decision: ACCEPT-PROPOSAL (won) or
    REJECT-PROPOSAL (lost)."""

    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        perf = msg.get_metadata("performative")
        if perf == ACCEPT_PROPOSAL:
            # We won the robot — mark en_route so we stop bidding
            self.agent.beliefs.update("patrol_status", "en_route")
            self.agent.log(f"won patrol auction ({msg.thread}) -> robot en route")
        elif perf == REJECT_PROPOSAL:
            self.agent.log(f"lost patrol auction ({msg.thread})")


class BDIDeliberationCycle(PeriodicBehaviour):
    """The deliberation loop: threat fusion ->desires ->plan ->intention."""

    async def run(self):
        beliefs = self.agent.beliefs

        # ── 0. Settle: let a burst of correlated events finish ───
        if time.time() - self.agent.last_perception < SETTLE_SECONDS:
            return

        # ── 1. Threat fusion (zone-aware, per the design table) ──
        threat, interpretation = fuse(self.agent.zone_id, beliefs)
        prev = beliefs.get("threat_level")
        beliefs.update("threat_level", threat)
        beliefs.update("interpretation", interpretation)
        if threat != prev:
            self.agent.log(f"threat={threat} ({interpretation})")

        # ── 2. Desire generation (log only when it changes) ──
        names = [d.name for d in generate_desires(beliefs)]
        if names != self.agent.last_desires:
            self.agent.last_desires = names
            if names:
                self.agent.log(f"desires: {names}")

        # ── 2b. Announce patrol demand (Contract Net) ────────
        # We don't request a specific robot directly; we signal that this zone
        # wants patrol. The PatrolAgent auctions its time to the highest bidder.
        if threat >= settings.THREAT_HIGH and beliefs.get("patrol_status") != "en_route":
            await self.send(build_msg(
                settings.PATROL_JID, REQUEST,
                {"action": "patrol_wanted", "zone": self.agent.zone_id},
            ))

        # ── 3. Plan selection (utility-weighted) ─────────────
        plan = self.agent.plan_library.select(beliefs)
        if plan is None:
            return

        # ── 4. Intention execution ───────────────────────────
        if plan.name != self.agent.current_intention:
            self.agent.current_intention = plan.name
            self.agent.log(f"intention adopted: {plan.name}")
            await plan.body(beliefs, self.agent)
            self.agent.current_intention = None


# ════════════════════════════════════════════════════════════
#  Plan bodies (intentions)
# ════════════════════════════════════════════════════════════

async def plan_raise_alert(beliefs, agent):
    """Inform the AlertAgent — human operator notification."""
    msg = build_msg(
        to=settings.ALERT_JID,
        performative=INFORM,
        body={
            "event": "alert",
            "zone": agent.zone_id,
            "threat_level": beliefs.get("threat_level"),
            "details": beliefs.snapshot(),
        },
    )
    await agent.deliberation_behaviour.send(msg)
    # Remember we've alerted at this level so we don't spam every cycle
    beliefs.update("alerted_level", beliefs.get("threat_level"))
    agent.log(f"INFORM alert ->{settings.ALERT_JID}")


async def plan_verify_identity(beliefs, agent):
    """Request FaceIDAgent re-verification (e.g. second capture)."""
    msg = build_msg(
        to=settings.FACEID_JID,
        performative=REQUEST,
        body={"action": "reverify", "zone": agent.zone_id},
    )
    await agent.deliberation_behaviour.send(msg)
    agent.log("REQUEST reverify ->FaceIDAgent")


# ════════════════════════════════════════════════════════════
#  Agent
# ════════════════════════════════════════════════════════════

class ZoneCoordinatorAgent(Agent):
    """Deliberative BDI coordinator for a single facility zone."""

    def __init__(self, jid, password, zone_id: str, **kwargs):
        super().__init__(jid, password, **kwargs)
        self.zone_id = zone_id
        self.beliefs = BeliefBase()
        self.beliefs.update("zone_id", zone_id)
        self.plan_library = PlanLibrary()
        self.current_intention: str | None = None
        self.deliberation_behaviour = None
        self.last_perception = 0.0
        self.last_desires = None

    def log(self, text: str):
        print(f"[ZC:{self.zone_id}] {text}")
        dashboard_log.push(f"ZC:{self.zone_id}", text)

    def _build_plan_library(self):
        lib = self.plan_library

        # Note: patrol is no longer a direct plan — it is allocated through the
        # Contract Net auction (see CFPResponder + the patrol_wanted announce).

        lib.register(Plan(
            name="raise_alert",
            trigger=lambda b: b.get("threat_level", 0) >= settings.THREAT_CRITICAL,
            # Only alert once per escalation level (don't spam every cycle)
            context=lambda b: b.get("alerted_level") != b.get("threat_level"),
            utility=lambda b: 20.0,           # always outranks patrol at critical
            body=plan_raise_alert,
        ))

        lib.register(Plan(
            name="verify_identity",
            trigger=lambda b: bool(b.get("unknown_face")) and not b.get("cyber_anomaly"),
            context=lambda b: b.get("threat_level", 0) < settings.THREAT_HIGH,
            utility=lambda b: 5.0,
            body=plan_verify_identity,
        ))

    async def setup(self):
        self.log("starting (deliberative BDI)")
        self._build_plan_library()

        # Belief revision: only INFORM messages
        inform_template = Template()
        inform_template.set_metadata("performative", INFORM)
        self.add_behaviour(PerceptionListener(), inform_template)

        # Contract Net: bid when the patrol auctioneer calls for proposals
        cfp_template = Template()
        cfp_template.set_metadata("performative", CFP)
        self.add_behaviour(CFPResponder(), cfp_template)

        # Contract Net: handle the auction outcome (won / lost)
        accept_template = Template()
        accept_template.set_metadata("performative", ACCEPT_PROPOSAL)
        reject_template = Template()
        reject_template.set_metadata("performative", REJECT_PROPOSAL)
        self.add_behaviour(AuctionResultHandler(), accept_template | reject_template)

        # Deliberation cycle (snappy enough that escalations are ready to bid)
        self.deliberation_behaviour = BDIDeliberationCycle(period=1)
        self.add_behaviour(self.deliberation_behaviour)
