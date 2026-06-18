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
from utils import build_msg, parse_body
from utils.messaging import (
    REQUEST, INFORM, ACCEPT_PROPOSAL, REJECT_PROPOSAL,
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


class WebotsNavigation:
    """Navigation layer for Webots integration.

    Sends patrol commands to the WebotsBridge; the security_supervisor
    controller moves the physical robot and signals back when done.
    The 2D dashboard position (agent.pos) is updated in sync so the
    web dashboard remains accurate.
    """

    async def move(self, agent, target: tuple,
                   abort_event: asyncio.Event = None) -> bool:
        from bridges import get_bridge
        bridge = get_bridge()

        zone = settings.WEBOTS_POS_TO_ZONE.get(target, "__base__")
        bridge.put_patrol_command({"action": "go_to", "zone": zone})

        arrived = await bridge.wait_arrived(abort_event)
        if not arrived:
            # Preempted mid-flight — tell the supervisor to stop the robot
            bridge.put_patrol_command({"action": "cancel"})
            return False

        agent.pos = target
        return True

    async def scan_zone(self, zone: str,
                        abort_event: asyncio.Event = None) -> str:
        from bridges import get_bridge
        bridge = get_bridge()
        bridge.put_patrol_command({"action": "scan", "zone": zone})
        return await bridge.wait_scan_result(abort_event)


# ════════════════════════════════════════════════════════════
#  Behaviours
# ════════════════════════════════════════════════════════════

class DemandListener(CyclicBehaviour):
    """Collect patrol_wanted announcements from ZoneCoordinators.

    Each message now carries the zone's current threat priority so the
    PatrolAgent can decide locally without a CFP/PROPOSE round-trip.
    Bids are stored in agent.pending_demands[zone] = priority so that
    AuctionBehaviour always sees the most urgent current demand.
    """

    async def run(self):
        msg = await self.receive(timeout=1)
        if not msg:
            return
        body = parse_body(msg)
        if body.get("action") != "patrol_wanted":
            return
        zone     = body.get("zone")
        priority = body.get("priority", settings.THREAT_HIGH)
        if zone and zone in settings.ZONES:
            agent = self.agent
            # Keep the highest priority seen for this zone
            if priority > agent.pending_demands.get(zone, 0):
                agent.pending_demands[zone] = priority
            agent.demand = True


class AuctionBehaviour(PeriodicBehaviour):
    """Direct-dispatch auctioneer — no CFP/PROPOSE round-trip.

    ZoneCoordinators include their current bid in each patrol_wanted
    message. DemandListener stores these in agent.pending_demands.
    Here we pick the highest-priority pending zone and dispatch or
    preempt immediately.  Ties go to the incumbent mission.

    The scan phase is NEVER interrupted — only travel is preemptable.
    """

    def _live_demands(self, agent) -> dict[str, int]:
        """Read ZC beliefs directly (in-process, zero XMPP latency).

        pending_demands (XMPP) is stale by design — ZCs keep sending
        patrol_wanted until ACCEPT_PROPOSAL arrives (~18 s later).
        We MUST cross-check patrol_status from the ZC belief base so a
        zone that is already en_route never sneaks back in.
        """
        demands: dict[str, int] = {}
        for zone, zc in agent.zone_coordinators.items():
            threat  = zc.beliefs.get("threat_level", 0)
            status  = zc.beliefs.get("patrol_status")
            eligible = (threat >= settings.THREAT_HIGH
                        and status not in ("en_route", "intruder_confirmed"))
            if eligible:
                bid = max(threat, agent.pending_demands.get(zone, 0))
                demands[zone] = bid
        return demands

    async def run(self):
        agent = self.agent

        # Never interrupt an active scan
        if agent.phase == "scanning":
            return

        # Merge XMPP-delivered bids with direct ZC belief snapshot
        demands = self._live_demands(agent)
        if not demands:
            agent.demand = False
            return

        # Sort candidates: highest priority first; on tie, incumbent wins
        candidates = sorted(
            demands.items(),
            key=lambda kv: (kv[1], kv[0] == agent.current_zone),
            reverse=True,
        )
        win_zone, win_bid = candidates[0]
        win_jid = settings.ZONE_COORDINATOR_JIDS[win_zone]

        # Incumbent advantage: equal priority → let current mission finish
        if agent.busy and win_bid == agent.current_priority and win_zone == agent.current_zone:
            return

        should_accept = (not agent.busy) or (win_bid > agent.current_priority)

        if not should_accept:
            agent.log(f"bids rejected (busy '{agent.current_zone}'"
                      f" prio {agent.current_priority} >= {win_bid})")
            return

        # --- Accept winner -------------------------------------------------
        agent.demand = False
        agent.pending_demands.pop(win_zone, None)
        agent.auction_id += 1
        thread = f"auction-{agent.auction_id}"

        # Notify ZCs so they can update patrol_status (en_route / rejected)
        await self.send(build_msg(win_jid, ACCEPT_PROPOSAL,
                                  {"action": "patrol_zone", "zone": win_zone},
                                  thread=thread))
        for z, _pri in candidates[1:]:
            jid = settings.ZONE_COORDINATOR_JIDS.get(z)
            if jid:
                await self.send(build_msg(jid, REJECT_PROPOSAL,
                                          {"zone": z}, thread=thread))

        agent.last_auction = {
            "id": agent.auction_id,
            "bids": [[z, p] for z, p in candidates],
            "winner": win_zone,
        }
        agent.log(f"auction #{agent.auction_id}: winner '{win_zone}' (prio {win_bid})"
                  f" from {[(z, p) for z, p in candidates]}")

        if not agent.busy:
            agent.busy = True
            agent.current_priority = win_bid   # block cascade before run() starts
            agent.add_behaviour(
                PatrolMission(zone=win_zone, requester=win_jid,
                              thread=thread, priority=win_bid)
            )
        else:
            if agent.next_mission:
                old = agent.next_mission
                await self.send(build_msg(old["requester"], INFORM,
                                          {"event": "patrol_report",
                                           "zone": old["zone"], "status": "deferred"},
                                          thread=old["thread"]))
                agent.log(f"displaced queued '{old['zone']}' for '{win_zone}'")
            agent.next_mission = {
                "zone": win_zone, "requester": win_jid,
                "thread": thread, "priority": win_bid,
            }
            # Set priority immediately to prevent cascade re-preemption
            agent.current_priority = win_bid
            agent.abort_event.set()
            if agent.phase == "returning":
                agent.log(f"REDIRECT (returning) -> '{win_zone}' (prio {win_bid})")
            else:
                agent.log(f"PREEMPT '{agent.current_zone}' -> '{win_zone}' (prio {win_bid})")


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
            asyncio.ensure_future(self.send(build_msg(self.requester, INFORM, {
                "event": "patrol_report", "zone": self.zone, "status": "en_route",
            }, thread=self.thread)))

            # 1. Travel to the zone (animated across the floor plan)
            agent.phase = "traveling"
            agent.log(f"en route to '{self.zone}' (priority {self.priority})")
            reached = await agent.nav.move(
                agent, settings.ZONE_POS[self.zone], agent.abort_event
            )

            if not reached:
                asyncio.ensure_future(self.send(build_msg(self.requester, INFORM, {
                    "event": "patrol_report", "zone": self.zone,
                    "status": "preempted",
                }, thread=self.thread)))
                agent.log(f"'{self.zone}' preempted mid-route")
                return

            # 2. Inspect the zone (also interruptible)
            agent.phase = "scanning"
            result = await agent.nav.scan_zone(self.zone, agent.abort_event)
            if result == "preempted":
                asyncio.ensure_future(self.send(build_msg(self.requester, INFORM, {
                    "event": "patrol_report", "zone": self.zone,
                    "status": "preempted",
                }, thread=self.thread)))
                agent.log(f"'{self.zone}' scan preempted")
                return

            # Fire-and-forget: don't block the event loop waiting for pyjabber
            # to deliver the INFORM — the finally block must run immediately.
            asyncio.ensure_future(self.send(build_msg(self.requester, INFORM, {
                "event": "patrol_report", "zone": self.zone, "status": result,
            }, thread=self.thread)))
            agent.log(f"patrol of '{self.zone}' complete: {result}")

        finally:
            agent.abort_event.clear()
            if agent.next_mission:
                # Preempted or redirected: go directly to the new zone
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
                # Scan complete — drop priority and check for pending demands
                # BEFORE touching the bridge queue.  If a zone needs patrol
                # right now, dispatch directly (never send "go_to __base__").
                agent.current_priority = 0

                demands = agent.live_demands()
                if demands:
                    # Pick the highest-priority pending zone
                    candidates = sorted(demands.items(),
                                        key=lambda kv: kv[1], reverse=True)
                    win_zone, win_bid = candidates[0]
                    win_jid = settings.ZONE_COORDINATOR_JIDS[win_zone]
                    agent.auction_id += 1
                    thread = f"direct-{agent.auction_id}"
                    agent.current_priority = win_bid
                    agent.log(f"direct dispatch -> '{win_zone}' (prio {win_bid})"
                              " after scan, skipping base")
                    asyncio.ensure_future(self.send(build_msg(
                        win_jid, ACCEPT_PROPOSAL,
                        {"action": "patrol_zone", "zone": win_zone},
                        thread=thread,
                    )))
                    for z, _ in candidates[1:]:
                        jid = settings.ZONE_COORDINATOR_JIDS.get(z)
                        if jid:
                            asyncio.ensure_future(self.send(build_msg(
                                jid, REJECT_PROPOSAL, {"zone": z}, thread=thread,
                            )))
                    agent.add_behaviour(PatrolMission(
                        zone=win_zone, requester=win_jid,
                        thread=thread, priority=win_bid,
                    ))
                else:
                    # No pending demand → return to base.
                    # AuctionBehaviour handles redirects mid-journey via abort_event.
                    agent.phase = "returning"
                    await agent.nav.move(agent, settings.PATROL_BASE_POS, agent.abort_event)
                    agent.abort_event.clear()
                    if agent.next_mission:
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
        self.demand = False
        self.pending_demands: dict[str, int] = {}
        self.zone_coordinators: dict = {}
        self.auction_id = 0
        self.current_zone = None
        self.current_priority = 0
        self.current_requester = None
        self.next_mission = None
        self.last_auction = None
        self.pos = settings.PATROL_BASE_POS
        self.phase = "idle"
        self.nav = WebotsNavigation() if settings.WEBOTS_ENABLED else NavigationStub()
        self.abort_event = asyncio.Event()

    def live_demands(self) -> dict[str, int]:
        """Read ZC beliefs directly (in-process, zero XMPP latency).

        pending_demands (XMPP) is stale by design — ZCs keep sending
        patrol_wanted until ACCEPT_PROPOSAL arrives (~18 s later).
        We MUST cross-check patrol_status from the ZC belief base so
        a zone that is already en_route never sneaks back in.
        """
        demands: dict[str, int] = {}
        for zone, zc in self.zone_coordinators.items():
            threat  = zc.beliefs.get("threat_level", 0)
            status  = zc.beliefs.get("patrol_status")
            eligible = (threat >= settings.THREAT_HIGH
                        and status not in ("en_route", "intruder_confirmed"))
            if eligible:
                # Take the max of the live belief and any XMPP-delivered bid
                bid = max(threat, self.pending_demands.get(zone, 0))
                demands[zone] = bid
        return demands

    def log(self, text: str):
        print(f"[Patrol] {text}")
        dashboard_log.push("Patrol", text)

    async def setup(self):
        self.log("starting (hybrid: direct-dispatch auctioneer + RL nav stub)")

        # Collect patrol_wanted announcements (REQUEST) with embedded bid
        demand_tmpl = Template()
        demand_tmpl.set_metadata("performative", REQUEST)
        self.add_behaviour(DemandListener(), demand_tmpl)

        # Auction fires every 0.5 s — no gather window, no CFP round-trip.
        # Decides from pending_demands collected by DemandListener.
        self.add_behaviour(AuctionBehaviour(period=0.5))
