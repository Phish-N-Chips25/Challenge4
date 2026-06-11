"""
Train the patrol robot's NAVIGATION policy with PPO.

The policy learns to drive the Booster T1 from its current pose to a target
zone dispatched by the SIMAGIA multi-agent system.  Zone *selection* is the
MAS's job (Contract Net auction); this is the low-level "go to waypoint" layer.

Usage:
    python src/rl/train.py --config configs/ppo.yaml
"""

import argparse
from pathlib import Path

import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.env_util import make_vec_env

from env import OfficeNavEnv


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
    n_envs = alg_cfg.get("n_envs", 1)

    # ── Environments ─────────────────────────────────────────────────────
    # Vectorised for throughput; navigation rollouts are cheap (no Webots).
    env = make_vec_env(
        OfficeNavEnv, n_envs=n_envs, env_kwargs={"config": env_cfg}
    )
    eval_env = make_vec_env(
        OfficeNavEnv, n_envs=1, env_kwargs={"config": env_cfg}
    )

    # ── Callbacks ────────────────────────────────────────────────────────
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path="data/models/best",
        log_path=str(log_dir),
        eval_freq=max(cfg["evaluation"]["eval_freq"] // n_envs, 1),
        n_eval_episodes=cfg["evaluation"]["n_eval_episodes"],
        deterministic=True,
    )
    checkpoint_callback = CheckpointCallback(
        save_freq=max(50_000 // n_envs, 1),
        save_path="data/models/checkpoints",
        name_prefix="nav_ppo",
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

    print(f"Training PPO navigation policy for {alg_cfg['total_timesteps']} timesteps "
          f"({n_envs} parallel envs)...")
    model.learn(
        total_timesteps=alg_cfg["total_timesteps"],
        callback=[eval_callback, checkpoint_callback],
    )

    model.save("data/models/nav_ppo_final")
    print("Training complete. Model saved to data/models/nav_ppo_final.zip")


if __name__ == "__main__":
    main()
