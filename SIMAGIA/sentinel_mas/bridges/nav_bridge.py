"""Bridge: expose the RL PPO navigation policy to the MAS.

The trained policy lives in the sibling cyber-physical-security-system repo
(src/rl). This bridge adds that directory to sys.path and loads PPONavigator,
which is the drop-in replacement for patrol.NavigationStub (same move() /
scan_zone() interface, but drives a wall-aware planned route with the trained
policy and updates agent.pos in Webots metres).

It fails *soft*: if the RL stack, the model, or its dependencies
(stable-baselines3 / torch) aren't importable in the current environment — or
USE_PPO_NAV is turned off — it returns None and the caller keeps the legacy
NavigationStub. That lets the MAS run standalone (no torch/Webots) and switch
to the real policy just by running in the cyberpatrol env with USE_PPO_NAV=1.
"""

from __future__ import annotations

import sys

from config import settings


def make_navigator():
    """Return a PPONavigator, or None to signal "fall back to NavigationStub"."""
    if not settings.USE_PPO_NAV:
        return None
    try:
        if settings.RL_DIR not in sys.path:
            sys.path.insert(0, settings.RL_DIR)
        from policy_runner import PPONavigator   # noqa: E402  (path set above)
        return PPONavigator(settings.NAV_MODEL_PATH)
    except Exception as e:
        print(f"[nav_bridge] PPO navigator unavailable ({e!r}); "
              f"falling back to NavigationStub. "
              f"(Run in the cyberpatrol env with USE_PPO_NAV=1 to enable it.)")
        return None
