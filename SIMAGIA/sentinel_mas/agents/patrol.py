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
    2. The patrol broadcasts a CFP to all coordinators (call-for-proposals),
       even if already moving — auctions run continuously.
    3. Interested coordinators reply PROPOSE with a bid = their threat level.
    4. The patrol awards ACCEPT-PROPOSAL to the highest bidder:
       - If idle      → start mission immediately.
       - If busy and new bid > current mission priority → preempt: abort
         current movement, redirect to the new zone without returning to base.
       - If busy and new bid <= current priority → reject all bids (zone keeps
         its demand flag and re-bids in the next auction round).
"""

import asyncio
import math
import random

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour
from spade.template import Template

from config import settings
from bridges.nav_bridge import make_navigator
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

    async def move(self, agent, target: tuple,
                   abort_event: asyncio.Event = None) -> bool:
        """Glide agent.pos to `target` at settings.PATROL_SPEED units/sec.

        Returns True when the target is reached, False when abort_event fires
        mid-flight (preempted by a higher-priority auction winner).
        """
        sx, sy = agent.pos
        tx, ty = target
        dist = math.hypot(tx - sx, ty - sy)
        duration = max(dist / settings.PATROL_SPEED, 0.3)
        steps = max(int(duration / self.STEP), 1)
        for i in range(1, steps + 1):
            if abort_event and abort_event.is_set():
                return False
            f = i / steps
            agent.pos = (sx + (tx - sx) * f, sy + (ty - sy) * f)
            await asyncio.sleep(duration / steps)
        agent.pos = (tx, ty)
        return True

    async def scan_zone(self, _zone: str,
                        abort_event: asyncio.Event = None) -> str:
        """Inspect a zone.  Returns "preempted" if abort_event fires."""
        elapsed = 0.0
        interval = 0.1
        while elapsed < settings.PATROL_SCAN_SECONDS:
            if abort_event and abort_event.is_set():
                return "preempted"
            await asyncio.sleep(interval)
            elapsed += interval
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
    """Contract Net auctioneer.

    Runs regardless of whether the robot is busy, so that high-priority
    zones can preempt an ongoing lower-priority mission mid-flight.
    """

    BID_WINDOW = 1.0          # seconds to collect proposals

    async def run(self):
        agent = self.agent
        if not agent.demand:
            return

        # Gather: give zones that are still escalating time to announce so
        # near-simultaneous escalations compete in the SAME auction.
        await asyncio.sleep(settings.AUCTION_GATHER_SECONDS)

        agent.demand = False
        agent.auction_id += 1
        thread = f"auction-{agent.auction_id}"

        # 1. Call for proposals to every coordinator
        for jid in settings.ZONE_COORDINATOR_JIDS.values():
            await self.send(build_msg(jid, CFP, {"action": "patrol_auction"},
                                      thread=thread))
        agent.log(f"CFP auction #{agent.auction_id} -> {len(settings.ZONES)} zones"
                  f" (robot: {'busy prio=' + str(agent.current_priority) if agent.busy else 'idle'})")

        # 2. Collect bids for a short window
        bids = []
        deadline = asyncio.get_event_loop().time() + self.BID_WINDOW
        while asyncio.get_event_loop().time() < deadline:
            reply = await self.receive(timeout=0.2)
            if reply and reply.thread == thread:
                b = parse_body(reply)
                bids.append((b.get("bid", 0), b.get("score", 0.0),
                             b.get("zone"), str(reply.sender)))

        # The zone the robot is *already* travelling to is muted while
        # en_route (CFPResponder), so it never re-bids.  To make preemption a
        # genuine auction over all the options it has — not just a reaction to
        # whoever bids higher than current_priority — we inject the active
        # mission as a synthetic bidder.  The winner is then decided over
        # {real bids} ∪ {current mission}, with ties going to the incumbent.
        # Tuple layout: (bid, score, is_current, zone, jid)
        bids = [(b, s, 0, z, j) for (b, s, z, j) in bids]
        if agent.busy and agent.current_priority > 0 and agent.current_zone:
            bids.append((agent.current_priority, 0.0, 1,
                         agent.current_zone, agent.current_requester))

        if not bids:
            agent.log(f"auction #{agent.auction_id}: no bids")
            return

        # 3. Award: highest threat wins; on a tie the incumbent mission keeps
        #    the robot (is_current), then anomaly score breaks remaining ties.
        bids.sort(key=lambda x: (x[0], x[2], x[1]), reverse=True)
        win_bid, _, win_is_current, win_zone, win_jid = bids[0]
        agent.last_auction = {
            "id": agent.auction_id,
            "bids": [[z, bid] for bid, _, _, z, _ in bids],
            "winner": win_zone,
        }
        agent.log(f"auction #{agent.auction_id}: bids="
                  f"{[(z, bid) for bid, _, _, z, _ in bids]} -> winner '{win_zone}'")

        # The incumbent won its own auction → nothing to change, just clear the
        # losers and let the current mission run to completion.
        if win_is_current:
            for _, _, _, z, jid in bids:
                if jid != win_jid:
                    await self.send(build_msg(jid, REJECT_PROPOSAL,
                                              {"zone": z}, thread=thread))
            agent.log(f"auction #{agent.auction_id}: '{win_zone}'"
                      f" (prio {win_bid}) keeps the robot — current mission continues")
            return

        # Decide: accept winner only if idle or new mission outranks current
        should_accept = (not agent.busy) or (win_bid > agent.current_priority)

        if should_accept:
            await self.send(build_msg(win_jid, ACCEPT_PROPOSAL,
                                      {"action": "patrol_zone", "zone": win_zone},
                                      thread=thread))
            for _, _, _, z, jid in bids[1:]:
                if jid is not None:
                    await self.send(build_msg(jid, REJECT_PROPOSAL,
                                              {"zone": z}, thread=thread))

            if not agent.busy:
                # Robot idle → start immediately
                agent.busy = True
                agent.add_behaviour(
                    PatrolMission(zone=win_zone, requester=win_jid,
                                  thread=thread, priority=win_bid)
                )
            else:
                # Preempt: abort current movement, redirect without returning base
                if agent.next_mission:
                    # Displace previously queued mission
                    old = agent.next_mission
                    await self.send(build_msg(old["requester"], INFORM,
                                              {"event": "patrol_report",
                                               "zone": old["zone"],
                                               "status": "deferred"},
                                              thread=old["thread"]))
                    agent.log(f"displaced queued '{old['zone']}' (prio {old['priority']})"
                              f" for '{win_zone}' (prio {win_bid})")
                agent.next_mission = {
                    "zone": win_zone, "requester": win_jid,
                    "thread": thread, "priority": win_bid,
                }
                agent.abort_event.set()
                if agent.current_priority == 0:
                    agent.log(f"REDIRECT during return -> '{win_zone}' (prio {win_bid})")
                else:
                    agent.log(f"PREEMPT '{agent.current_zone}' (prio {agent.current_priority})"
                              f" -> '{win_zone}' (prio {win_bid})")
        else:
            # Current mission is equal or higher priority — reject all bids so
            # zones keep demand and re-bid once the robot finishes.
            for _, _, _, z, jid in bids:
                if jid is not None:
                    await self.send(build_msg(jid, REJECT_PROPOSAL,
                                              {"zone": z}, thread=thread))
            agent.log(f"auction #{agent.auction_id}: bids rejected"
                      f" (busy '{agent.current_zone}' prio {agent.current_priority} >= {win_bid})")


class PatrolMission(OneShotBehaviour):
    """Executes one patrol mission: navigate → scan → report.

    Checks agent.abort_event during travel and scan; if fired, the current
    mission is interrupted and agent.next_mission (set by AuctionBehaviour)
    is dispatched directly from the robot's current position.
    """

    def __init__(self, zone: str, requester: str, thread: str | None,
                 priority: int = 0):
        super().__init__()
        self.zone = zone
        self.requester = requester
        self.thread = thread
        self.priority = priority

    async def run(self):
        agent = self.agent
        agent.current_zone = self.zone
        agent.current_priority = self.priority
        agent.current_requester = self.requester
        try:
            # En-route status
            await self.send(build_msg(self.requester, INFORM, {
                "event": "patrol_report", "zone": self.zone, "status": "en_route",
            }, thread=self.thread))

            # 1. Travel to the zone (animated across the floor plan)
            agent.phase = "traveling"
            agent.log(f"en route to '{self.zone}' (priority {self.priority})")
            reached = await agent.nav.move(
                agent, settings.ZONE_POS[self.zone], agent.abort_event
            )

            if not reached:
                # Preempted mid-flight by a higher-priority auction winner
                await self.send(build_msg(self.requester, INFORM, {
                    "event": "patrol_report", "zone": self.zone,
                    "status": "preempted",
                }, thread=self.thread))
                agent.log(f"'{self.zone}' preempted mid-route")
                return

            # 10% chance the robot can't complete (exercise the FAILURE path)
            if random.random() >= 0.9:
                await self.send(build_msg(self.requester, INFORM, {
                    "event": "patrol_report", "zone": self.zone, "status": "failed",
                }, thread=self.thread))
                agent.log(f"FAILURE at '{self.zone}' (will re-auction)")
                return

            # 2. Inspect the zone (also interruptible)
            agent.phase = "scanning"
            result = await agent.nav.scan_zone(self.zone, agent.abort_event)
            if result == "preempted":
                await self.send(build_msg(self.requester, INFORM, {
                    "event": "patrol_report", "zone": self.zone,
                    "status": "preempted",
                }, thread=self.thread))
                agent.log(f"'{self.zone}' scan preempted")
                return

            await self.send(build_msg(self.requester, INFORM, {
                "event": "patrol_report", "zone": self.zone, "status": result,
            }, thread=self.thread))
            agent.log(f"patrol of '{self.zone}' complete: {result}")

        finally:
            agent.abort_event.clear()
            if agent.next_mission:
                # Preempted mid-mission: redirect directly, no base return
                next_m = agent.next_mission
                agent.next_mission = None
                agent.log(f"redirecting to '{next_m['zone']}' (priority {next_m['priority']})"
                          " from current position")
                agent.add_behaviour(PatrolMission(
                    zone=next_m["zone"],
                    requester=next_m["requester"],
                    thread=next_m["thread"],
                    priority=next_m["priority"],
                ))
            else:
                # Scan complete (or failed/preempted with no queued mission).
                # Drop priority to 0 NOW so auctions during the return journey
                # can immediately redirect the robot instead of waiting for it
                # to touch base — this also allows a preempted zone to win and
                # get scanned without the robot making a pointless base trip.
                agent.current_priority = 0
                agent.phase = "returning"
                await agent.nav.move(agent, settings.PATROL_BASE_POS, agent.abort_event)
                agent.abort_event.clear()
                if agent.next_mission:
                    # A zone won an auction while the robot was returning —
                    # go directly from current position, skip the base.
                    next_m = agent.next_mission
                    agent.next_mission = None
                    agent.log(f"redirecting during return to '{next_m['zone']}'"
                              f" (priority {next_m['priority']})")
                    agent.add_behaviour(PatrolMission(
                        zone=next_m["zone"],
                        requester=next_m["requester"],
                        thread=next_m["thread"],
                        priority=next_m["priority"],
                    ))
                else:
                    agent.busy = False
                    agent.current_zone = None
                    agent.current_requester = None
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
        self.current_priority = 0   # bid level of the active mission
        self.current_requester = None  # jid of the coordinator we're serving
        self.next_mission = None     # dict queued by AuctionBehaviour on preempt
        self.last_auction = None     # summary of the most recent auction
        self.pos = settings.PATROL_BASE_POS   # (x, y) in Webots metres
        self.phase = "idle"          # idle | traveling | scanning | returning
        # Real RL navigation policy when available (cyberpatrol env), else the
        # legacy point-glide stub — same move()/scan_zone() interface either way.
        self.nav = make_navigator() or NavigationStub()
        self.abort_event = asyncio.Event()   # set to interrupt current movement

    def log(self, text: str):
        print(f"[Patrol] {text}")
        dashboard_log.push("Patrol", text)

    async def setup(self):
        self.log(f"starting (hybrid: Contract Net auctioneer + {type(self.nav).__name__})")

        # Listen for "patrol_wanted" announcements (REQUEST)
        demand_tmpl = Template()
        demand_tmpl.set_metadata("performative", REQUEST)
        self.add_behaviour(DemandListener(), demand_tmpl)

        # Run auctions; this behaviour also collects the PROPOSE bids.
        # Period=1 so new auctions trigger within ~1 s of demand appearing.
        propose_tmpl = Template()
        propose_tmpl.set_metadata("performative", PROPOSE)
        self.add_behaviour(AuctionBehaviour(period=1), propose_tmpl)
