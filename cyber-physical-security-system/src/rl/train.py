"""
Train the patrol robot's NAVIGATION policy with PPO.

The policy learns to drive the Booster T1 from its current pose to a target
zone dispatched by the SIMAGIA multi-agent system.  Zone *selection* is the
MAS's job (Contract Net auction); this is the low-level "go to waypoint" layer.

Usage:
    python src/rl/train.py --config configs/ppo.yaml
"""

import argparse
import time
from pathlib import Path

import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, EvalCallback, CheckpointCallback
from stable_baselines3.common.env_util import make_vec_env

from env import OfficeNavEnv


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _fmt_time(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


class TrainProgressCallback(BaseCallback):
    """Prints step/speed/ETA every `print_freq` timesteps."""

    def __init__(self, print_freq: int = 10_000):
        super().__init__(verbose=0)
        self.print_freq = print_freq
        self._t0: float = 0.0

    def _on_training_start(self) -> None:
        self._t0 = time.time()
        total = self.locals["total_timesteps"]
        print(f"\n{'-' * 62}")
        print(f"  Training started  |  target: {total:,} steps")
        print(f"  Progress logged every {self.print_freq:,} steps")
        print(f"{'-' * 62}\n")

    def _on_step(self) -> bool:
        if self.num_timesteps % self.print_freq == 0:
            elapsed = time.time() - self._t0
            total = self.locals["total_timesteps"]
            speed = self.num_timesteps / max(elapsed, 1e-6)
            eta = (total - self.num_timesteps) / max(speed, 1e-6)
            pct = 100 * self.num_timesteps / total
            bar_filled = int(pct / 5)
            bar = "#" * bar_filled + "." * (20 - bar_filled)
            print(
                f"  [{bar}] {pct:5.1f}%"
                f"  {self.num_timesteps:>7,}/{total:,}"
                f"  |  {speed:,.0f} steps/s"
                f"  |  elapsed {_fmt_time(elapsed)}"
                f"  |  ETA {_fmt_time(eta)}"
            )
        return True

    def _on_training_end(self) -> None:
        elapsed = time.time() - self._t0
        print(f"\n{'-' * 62}")
        print(f"  Training complete  |  total time: {_fmt_time(elapsed)}")
        print(f"{'-' * 62}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/ppo.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    alg_cfg = cfg["algorithm"]
    env_cfg = cfg["env"]
    n_envs = alg_cfg.get("n_envs", 1)

    # Vectorised for throughput; navigation rollouts are cheap (no Webots).
    env = make_vec_env(
        OfficeNavEnv, n_envs=n_envs, env_kwargs={"config": env_cfg}
    )
    eval_env = make_vec_env(
        OfficeNavEnv, n_envs=1, env_kwargs={"config": env_cfg}
    )

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
        verbose=2,
    )
    progress_callback = TrainProgressCallback(
        print_freq=alg_cfg.get("progress_freq", 10_000),
    )

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
        verbose=0,
        tensorboard_log=str(log_dir),
        device=alg_cfg.get("device", "cpu"),
    )

    print(f"Training PPO navigation policy for {alg_cfg['total_timesteps']:,} timesteps "
          f"({n_envs} parallel envs)...")
    model.learn(
        total_timesteps=alg_cfg["total_timesteps"],
        callback=[eval_callback, checkpoint_callback, progress_callback],
    )

    model.save("data/models/nav_ppo_final")
    print("Model saved to data/models/nav_ppo_final.zip")


if __name__ == "__main__":
    main()
