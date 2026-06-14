"""
Quick sanity-check for OfficeNavEnv — no external dependencies needed.

Validates the navigation environment against Gymnasium's checker, then runs
a short PPO training pass to confirm the full pipeline works before kicking
off a full run.

Usage:
    python src/rl/mock_env.py
"""

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env

from env import OfficeNavEnv


def evaluate(model, env, n_episodes: int = 20, name: str = "Policy"):
    arrivals, distances, rewards = [], [], []
    for _ in range(n_episodes):
        obs, _ = env.reset()
        ep_reward = 0.0
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, r, terminated, truncated, info = env.step(action)
            ep_reward += r
            done = terminated or truncated
        arrivals.append(float(info["arrived"]))
        distances.append(float(info["distance"]))
        rewards.append(ep_reward)

    print(f"\n{'=' * 55}")
    print(f"  {name}")
    print(f"{'=' * 55}")
    print(f"  Arrival rate:    {np.mean(arrivals):.0%}")
    print(f"  Final distance:  {np.mean(distances):.2f} m")
    print(f"  Episode reward:  {np.mean(rewards):.1f}")
    print(f"{'=' * 55}")
    return {"arrival_rate": float(np.mean(arrivals)), "reward": float(np.mean(rewards))}


class RandomBaseline:
    def __init__(self, env):
        self._env = env

    def predict(self, obs, **_):
        return self._env.action_space.sample(), None


class StraightLineBaseline:
    """Always command max forward speed, zero lateral/yaw — ignores heading."""
    def predict(self, obs, **_):
        return np.array([1.0, 0.0, 0.0], dtype=np.float32), None


if __name__ == "__main__":
    print("=" * 55)
    print("  CyberPatrol — OfficeNavEnv sanity check")
    print("=" * 55)

    env = OfficeNavEnv()

    print("\n[1/3] Gymnasium compatibility check...")
    check_env(env, warn=True)
    print("  OK\n")

    print("[2/3] PPO training (30k steps)...")
    model = PPO(
        "MlpPolicy", env,
        learning_rate=3e-4, n_steps=512, batch_size=64,
        n_epochs=10, gamma=0.99, verbose=0, device="cpu",
    )
    model.learn(total_timesteps=30_000)
    print("  Done\n")

    print("[3/3] Evaluation (20 episodes each)...")
    eval_env = OfficeNavEnv()
    ppo_result = evaluate(model, eval_env, name="PPO (30k steps)")
    rand_result = evaluate(RandomBaseline(eval_env), eval_env, name="Random baseline")
    sl_result = evaluate(StraightLineBaseline(), eval_env, name="Straight-line baseline")

    print("\nSummary:")
    print(f"  {'Policy':<25} {'Arrival':>8} {'Reward':>10}")
    print(f"  {'-' * 45}")
    for r in [ppo_result, rand_result, sl_result]:
        label = ["PPO (30k)", "Random", "Straight-line"][
            [ppo_result, rand_result, sl_result].index(r)
        ]
        print(f"  {label:<25} {r['arrival_rate']:>7.0%} {r['reward']:>10.1f}")
    print()
