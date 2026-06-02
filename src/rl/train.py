"""
Train the patrol agent with PPO.

Usage:
    python src/rl/train.py --config configs/ppo.yaml
"""

import argparse
from pathlib import Path

import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback

from env import OfficePatrolEnv


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/ppo.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    alg_cfg = cfg["algorithm"]
    env_cfg = cfg["env"]

    # ── Environment ──────────────────────────────────────────────────────
    env = OfficePatrolEnv(config=env_cfg)
    eval_env = OfficePatrolEnv(config=env_cfg)

    # ── Callbacks ────────────────────────────────────────────────────────
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path="data/models/best",
        log_path=str(log_dir),
        eval_freq=cfg["evaluation"]["eval_freq"],
        n_eval_episodes=cfg["evaluation"]["n_eval_episodes"],
        deterministic=True,
    )
    checkpoint_callback = CheckpointCallback(
        save_freq=50_000,
        save_path="data/models/checkpoints",
        name_prefix="patrol_ppo",
    )

    # ── Training ─────────────────────────────────────────────────────────
    model = PPO(
        policy=alg_cfg["policy"],
        env=env,
        learning_rate=alg_cfg["learning_rate"],
        n_steps=alg_cfg["n_steps"],
        batch_size=alg_cfg["batch_size"],
        n_epochs=alg_cfg["n_epochs"],
        gamma=alg_cfg["gamma"],
        gae_lambda=alg_cfg["gae_lambda"],
        clip_range=alg_cfg["clip_range"],
        verbose=1,
        tensorboard_log=str(log_dir),
    )

    print(f"Training PPO for {alg_cfg['total_timesteps']} timesteps...")
    model.learn(
        total_timesteps=alg_cfg["total_timesteps"],
        callback=[eval_callback, checkpoint_callback],
    )

    model.save("data/models/patrol_ppo_final")
    print("Training complete. Model saved to data/models/patrol_ppo_final.zip")


if __name__ == "__main__":
    main()
