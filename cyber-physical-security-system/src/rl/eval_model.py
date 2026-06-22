"""
Evaluate a trained PPO navigation policy against the office layout.

Tests the final model, the best checkpoint, or a specific model file.
Reports overall metrics and a per-zone breakdown so you can see which
zones the policy handles well and which ones it struggles with.

Usage:
    python eval_model.py                             # final + best models
    python eval_model.py --model data/models/nav_ppo_final
    python eval_model.py --episodes 200
"""

import argparse
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

from env import OfficeNavEnv


def evaluate(model, env: OfficeNavEnv, n_episodes: int) -> dict:
    zone_stats = {z: {"attempts": 0, "arrivals": 0, "rewards": [], "distances": []}
                  for z in env.zones}
    all_rewards, all_dists, all_lengths, all_arrivals = [], [], [], []

    # Evaluate the 8 named DEPLOYMENT zones explicitly (round-robin, balanced).
    # Training samples random goal points for generalisation; evaluation targets
    # the actual zones via options["goal_zone"] so the per-zone breakdown is
    # meaningful. Start position stays random (set in reset), so each zone is
    # tested from varied approaches.
    zones = env.zones
    for ep in range(n_episodes):
        goal_zone = zones[ep % len(zones)]
        obs, _ = env.reset(options={"goal_zone": goal_zone})
        done, ep_reward, steps = False, 0.0, 0

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            ep_reward += reward
            steps += 1
            done = terminated or truncated

        arrived = bool(info["arrived"])
        dist    = float(info["distance"])

        all_rewards.append(ep_reward)
        all_dists.append(dist)
        all_lengths.append(steps)
        all_arrivals.append(arrived)

        zone_stats[goal_zone]["attempts"] += 1
        zone_stats[goal_zone]["arrivals"] += int(arrived)
        zone_stats[goal_zone]["rewards"].append(ep_reward)
        zone_stats[goal_zone]["distances"].append(dist)

    return {
        "arrival_rate":    float(np.mean(all_arrivals)),
        "mean_reward":     float(np.mean(all_rewards)),
        "mean_distance":   float(np.mean(all_dists)),
        "mean_ep_length":  float(np.mean(all_lengths)),
        "zone_stats":      zone_stats,
    }


def print_report(label: str, results: dict, n_episodes: int) -> None:
    w = 58
    print(f"\n{'=' * w}")
    print(f"  {label}")
    print(f"  {n_episodes} episodes, deterministic policy")
    print(f"{'=' * w}")
    print(f"  Arrival rate   : {results['arrival_rate']:>6.1%}")
    print(f"  Mean reward    : {results['mean_reward']:>8.2f}")
    print(f"  Final distance : {results['mean_distance']:>8.2f} m")
    print(f"  Episode length : {results['mean_ep_length']:>8.1f} / 400 steps")

    print(f"\n  Per-zone breakdown:")
    print(f"  {'Zone':<16} {'Attempts':>8} {'Arrived':>8} {'Rate':>7} {'Dist':>8}")
    print(f"  {'-' * 52}")

    zone_stats = results["zone_stats"]
    for zone in sorted(zone_stats, key=lambda z: -zone_stats[z]["attempts"]):
        s = zone_stats[zone]
        if s["attempts"] == 0:
            continue
        rate = s["arrivals"] / s["attempts"]
        dist = np.mean(s["distances"]) if s["distances"] else float("nan")
        bar  = "#" * int(rate * 10) + "." * (10 - int(rate * 10))
        print(f"  {zone:<16} {s['attempts']:>8} {s['arrivals']:>8} "
              f"  [{bar}] {rate:>4.0%}  {dist:>5.2f}m")

    print(f"{'=' * w}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",    type=str, default=None,
                        help="Path to a specific model zip (without .zip)")
    parser.add_argument("--episodes", type=int, default=100,
                        help="Episodes per model (default: 100)")
    parser.add_argument("--config",   type=str, default="../../configs/ppo.yaml",
                        help="Config file for the environment")
    args = parser.parse_args()

    # Load environment config if available
    env_cfg = None
    cfg_path = Path(args.config)
    if cfg_path.exists():
        import yaml
        with open(cfg_path) as f:
            env_cfg = yaml.safe_load(f).get("env", None)

    # Decide which models to test
    if args.model:
        candidates = [(Path(args.model).stem, args.model)]
    else:
        candidates = [
            ("Final model  (nav_ppo_final)",    "data/models/nav_ppo_final"),
            ("Best model   (best checkpoint)",  "data/models/best/best_model"),
        ]

    results_all = []
    for label, path in candidates:
        model_path = Path(path)
        if not model_path.with_suffix(".zip").exists() and not model_path.exists():
            print(f"  [skip] {label} — not found at {path}")
            continue
        print(f"\nLoading {label} ...")
        model = PPO.load(str(model_path))
        env   = OfficeNavEnv(config=env_cfg)
        res   = evaluate(model, env, args.episodes)
        results_all.append((label, res))
        print_report(label, res, args.episodes)

    if len(results_all) == 2:
        (la, ra), (lb, rb) = results_all
        diff = rb["arrival_rate"] - ra["arrival_rate"]
        winner = lb if diff > 0 else la
        print(f"\n  --> Use '{winner.split('(')[1].rstrip(')')}' "
              f"({'best' if diff > 0 else 'final'} wins by "
              f"{abs(diff):.0%} arrival rate)\n")


if __name__ == "__main__":
    main()
