"""Lightweight BDI reasoning engine for ZoneCoordinatorAgents.

Implements:
- Belief base (key-value store with timestamps)
- Desire generation from beliefs
- Plan library with trigger conditions, context guards, and utility weights
- Intention selection via utility-weighted plan ranking
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


# ── Belief base ──────────────────────────────────────────────
class BeliefBase:
    """Simple key→(value, timestamp) store."""

    def __init__(self) -> None:
        self._beliefs: dict[str, tuple[Any, float]] = {}

    def update(self, key: str, value: Any) -> None:
        self._beliefs[key] = (value, time.time())

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._beliefs.get(key)
        return entry[0] if entry else default

    def remove(self, key: str) -> None:
        self._beliefs.pop(key, None)

    def age(self, key: str) -> float | None:
        """Seconds since last update, or None if absent."""
        entry = self._beliefs.get(key)
        return (time.time() - entry[1]) if entry else None

    def snapshot(self) -> dict[str, Any]:
        return {k: v for k, (v, _) in self._beliefs.items()}

    def __contains__(self, key: str) -> bool:
        return key in self._beliefs


# ── Plan library ─────────────────────────────────────────────
@dataclass
class Plan:
    """A BDI plan with trigger, context guard, utility, and body.

    Attributes
    ----------
    name : str
        Human-readable plan identifier.
    trigger : Callable[[BeliefBase], bool]
        Returns True when the plan's triggering event is present.
    context : Callable[[BeliefBase], bool]
        Returns True when the plan is applicable given current beliefs.
    utility : Callable[[BeliefBase], float]
        Returns a numeric utility score for plan ranking.
    body : Callable[[BeliefBase, "ZoneCoordinatorAgent"], Any]
        Coroutine or function that executes the plan.  Receives the
        belief base and the agent reference so it can send messages.
    """

    name: str
    trigger: Callable[[BeliefBase], bool]
    context: Callable[[BeliefBase], bool]
    utility: Callable[[BeliefBase], float]
    body: Callable  # async def body(beliefs, agent) -> None


class PlanLibrary:
    """Collection of plans with utility-weighted selection."""

    def __init__(self) -> None:
        self._plans: list[Plan] = []

    def register(self, plan: Plan) -> None:
        self._plans.append(plan)

    def applicable(self, beliefs: BeliefBase) -> list[Plan]:
        """Return plans whose trigger AND context hold."""
        return [
            p for p in self._plans
            if p.trigger(beliefs) and p.context(beliefs)
        ]

    def select(self, beliefs: BeliefBase) -> Plan | None:
        """Select the highest-utility applicable plan."""
        candidates = self.applicable(beliefs)
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.utility(beliefs))


# ── Desire generator ─────────────────────────────────────────
@dataclass
class Desire:
    """A named goal with priority."""
    name: str
    priority: float = 1.0
    params: dict = field(default_factory=dict)


def generate_desires(beliefs: BeliefBase) -> list[Desire]:
    """Derive desires from current beliefs.

    Override or extend this function per zone to add zone-specific
    desire generation logic.
    """
    desires: list[Desire] = []

    threat = beliefs.get("threat_level", 0)
    if threat >= 2:
        desires.append(Desire("dispatch_patrol", priority=threat, params={"zone": beliefs.get("zone_id")}))
    if threat >= 3:
        desires.append(Desire("lockdown_zone", priority=threat + 1, params={"zone": beliefs.get("zone_id")}))

    # Unrecognised face without matching cyber event
    if beliefs.get("unknown_face") and not beliefs.get("cyber_anomaly"):
        desires.append(Desire("verify_identity", priority=1.5))

    # Cyber anomaly without physical presence
    if beliefs.get("cyber_anomaly") and not beliefs.get("physical_presence"):
        desires.append(Desire("investigate_cyber", priority=2.0))

    return desires
