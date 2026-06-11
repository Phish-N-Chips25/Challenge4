"""PatrolAgent — hybrid architecture (vertical layered).

High level : Contract Net auctioneer for its own (single-robot) time, plus
             BDI mission execution.
Low level  : RL navigation (PPO / stable-baselines3) at the velocity
             interface — STUBBED here; replaced by the real policy
             when Webots/ROS2 is integrated.

Negotiation (Contract Net Protocol)
-----------------------------------
The patrol robot is a scarce shared resource (one robot, five zones).  When
zones compete for it, the patrol runs an auction:

    1. A ZoneCoordinator that wants patrol announces interest (REQUEST
       patrol_wanted).
    2. When free and there is demand, the patrol broadcasts a CFP to all
       coordinators (call-for-proposals).
    3. Interested coordinators reply PROPOSE with a bid = their threat level.
    4. The patrol awards ACCEPT-PROPOSAL to the highest bidder and
       REJECT-PROPOSAL to the rest, then executes that one mission.
"""

import asyncio
import math
import random

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour
from spade.template import Template

from config import settings
from utils import build_msg, parse_body
from utils.messaging import (
    REQUEST, INFORM, CFP, PROPOSE, ACCEPT_PROPOSAL, REJECT_PROPOSAL,
)
import dashboard_log


# ════════════════════════════════════════════════════════════
#  Low-level navigation stub (future: PPO policy → ROS2 /cmd_vel)
# ════════════════════════════════════════════════════════════

class NavigationStub:
    """Stand-in for the RL navigation layer.

    Real implementation will:
      1. Load a trained PPO policy (stable-baselines3)
      2. Subscribe to /odom and /scan via the ROS2 bridge
      3. Publish Twist commands to /cmd_vel
    Here we move a 2D point across the floor plan at a fixed speed so the
    dashboard can show the robot travelling.
    """

    STEP = 0.12          # seconds between position updates

    async def move(self, agent, target: tuple) -> None:
        """Glide agent.pos to `target` at settings.PATROL_SPEED units/sec."""
        sx, sy = agent.pos
        tx, ty = target
        dist = math.hypot(tx - sx, ty - sy)
        duration = max(dist / settings.PATROL_SPEED, 0.3)
        steps = max(int(duration / self.STEP), 1)
        for i in range(1, steps + 1):
            f = i / steps
            agent.pos = (sx + (tx - sx) * f, sy + (ty - sy) * f)
            await asyncio.sleep(duration / steps)
        agent.pos = (tx, ty)

    async def scan_zone(self, zone: str) -> str:
        await asyncio.sleep(settings.PATROL_SCAN_SECONDS)
        # Simulated inspection outcome
        return random.choice(["clear", "clear", "clear", "intruder_confirmed"])


# ════════════════════════════════════════════════════════════
#  Behaviours
# ════════════════════════════════════════════════════════════

class DemandListener(CyclicBehaviour):
    """Note which coordinators want patrol (REQUEST patrol_wanted).

    This only *flags* that there is demand; the actual choice is made by the
    auction.  Keeping a flag (instead of acting immediately) is what lets the
    auction pick the most urgent zone rather than the first to ask."""

    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        if parse_body(msg).get("action") == "patrol_wanted":
            self.agent.demand = True


class AuctionBehaviour(PeriodicBehaviour):
    """Contract Net auctioneer.  When free and there is demand, run one
    round: CFP -> collect PROPOSE bids -> award ACCEPT/REJECT -> dispatch."""

    BID_WINDOW = 1.0          # seconds to collect proposals

    async def run(self):
        agent = self.agent
        if agent.busy or not agent.demand:
            return

        # 0. Gather: give zones that are still escalating time to announce,
        #    so near-simultaneous escalations compete in the SAME auction
        #    (prevents the robot rushing to whichever zone escalated first).
        await asyncio.sleep(settings.AUCTION_GATHER_SECONDS)

        agent.demand = False
        agent.auction_id += 1
        thread = f"auction-{agent.auction_id}"

        # 1. Call for proposals to every coordinator
        for jid in settings.ZONE_COORDINATOR_JIDS.values():
            await self.send(build_msg(jid, CFP, {"action": "patrol_auction"},
                                      thread=thread))
        agent.log(f"CFP auction #{agent.auction_id} -> {len(settings.ZONES)} zones")

        # 2. Collect bids for a short window
        bids = []
        deadline = asyncio.get_event_loop().time() + self.BID_WINDOW
        while asyncio.get_event_loop().time() < deadline:
            reply = await self.receive(timeout=0.2)
            if reply and reply.thread == thread:
                b = parse_body(reply)
                bids.append((b.get("bid", 0), b.get("score", 0.0),
                             b.get("zone"), str(reply.sender)))

        if not bids:
            agent.log(f"auction #{agent.auction_id}: no bids")
            return

        # 3. Award: highest threat wins (tie-break by anomaly score)
        bids.sort(key=lambda x: (x[0], x[1]), reverse=True)
        win_bid, _, win_zone, win_jid = bids[0]
        agent.last_auction = {
            "id": agent.auction_id,
            "bids": [[z, bid] for bid, _, z, _ in bids],
            "winner": win_zone,
        }
        agent.log(f"auction #{agent.auction_id}: bids="
                  f"{[(z, bid) for bid, _, z, _ in bids]} -> winner '{win_zone}'")

        await self.send(build_msg(win_jid, ACCEPT_PROPOSAL,
                                  {"action": "patrol_zone", "zone": win_zone},
                                  thread=thread))
        for _, _, z, jid in bids[1:]:
            await self.send(build_msg(jid, REJECT_PROPOSAL,
                                      {"zone": z}, thread=thread))

        # 4. Execute the awarded mission
        agent.busy = True
        agent.add_behaviour(
            PatrolMission(zone=win_zone, requester=win_jid, thread=thread)
        )


class PatrolMission(OneShotBehaviour):
    """Executes one patrol mission: navigate → scan → report."""

    def __init__(self, zone: str, requester: str, thread: str | None):
        super().__init__()
        self.zone = zone
        self.requester = requester
        self.thread = thread

    async def run(self):
        agent = self.agent
        agent.current_zone = self.zone
        try:
            # En-route status
            await self.send(build_msg(self.requester, INFORM, {
                "event": "patrol_report", "zone": self.zone, "status": "en_route",
            }, thread=self.thread))

            # 1. Travel to the zone (animated across the floor plan)
            agent.phase = "traveling"
            agent.log(f"en route to '{self.zone}'")
            await agent.nav.move(agent, settings.ZONE_POS[self.zone])

            # 10% chance the robot can't complete (exercise the FAILURE path)
            if random.random() >= 0.9:
                await self.send(build_msg(self.requester, INFORM, {
                    "event": "patrol_report", "zone": self.zone, "status": "failed",
                }, thread=self.thread))
                agent.log(f"FAILURE at '{self.zone}' (will re-auction)")
                return

            # 2. Inspect the zone
            agent.phase = "scanning"
            result = await agent.nav.scan_zone(self.zone)
            await self.send(build_msg(self.requester, INFORM, {
                "event": "patrol_report", "zone": self.zone, "status": result,
            }, thread=self.thread))
            agent.log(f"patrol of '{self.zone}' complete: {result}")

        finally:
            # 3. Return to base (also animated), then go idle
            agent.phase = "returning"
            await agent.nav.move(agent, settings.PATROL_BASE_POS)
            agent.busy = False
            agent.current_zone = None
            agent.phase = "idle"


# ════════════════════════════════════════════════════════════
#  Agent
# ════════════════════════════════════════════════════════════

class PatrolAgent(Agent):
    def __init__(self, jid, password, **kwargs):
        super().__init__(jid, password, **kwargs)
        self.busy = False
        self.demand = False          # set when a coordinator wants patrol
        self.auction_id = 0
        self.current_zone = None     # zone currently being patrolled
        self.last_auction = None     # summary of the most recent auction
        self.pos = settings.PATROL_BASE_POS   # (x, y) on the 2D map
        self.phase = "idle"          # idle | traveling | scanning | returning
        self.nav = NavigationStub()

    def log(self, text: str):
        print(f"[Patrol] {text}")
        dashboard_log.push("Patrol", text)

    async def setup(self):
        self.log("starting (hybrid: Contract Net auctioneer + RL nav stub)")

        # Listen for "patrol_wanted" announcements (REQUEST)
        demand_tmpl = Template()
        demand_tmpl.set_metadata("performative", REQUEST)
        self.add_behaviour(DemandListener(), demand_tmpl)

        # Run auctions; this behaviour also collects the PROPOSE bids
        propose_tmpl = Template()
        propose_tmpl.set_metadata("performative", PROPOSE)
        self.add_behaviour(AuctionBehaviour(period=2), propose_tmpl)
