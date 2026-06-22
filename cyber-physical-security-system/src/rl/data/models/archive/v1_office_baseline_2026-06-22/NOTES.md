# Policy archive — v1 "office baseline"

Snapshot date: 2026-06-22

## What this is
The first fully-trained PPO navigation policy, trained specifically on the
`sentinelmas_office.wbt` layout. Saved here before the v2 "layout-agnostic"
redesign, which changes the observation encoding and therefore makes the v2
weights **binary-incompatible** with this model.

## Files
- `nav_ppo_final.zip` — final model at 2,000,000 timesteps
- `best_model.zip`    — best model by eval reward during training
- `ppo.yaml`          — exact training config that produced these weights
- `env.py`            — the env at snapshot time; defines the obs/action
                        contract these weights expect. KEEP THIS — it is the
                        only way to reload/run this model correctly.

## Observation contract (10-D) — LAYOUT-BOUND
This is the encoding the v2 redesign removes:
    0  x position / x_half            (absolute, normalised by arena 10.0 m)
    1  y position / y_half            (absolute, normalised by arena  6.0 m)
    2  sin(heading)
    3  cos(heading)
    4  goal error forward / diag      (normalised by arena diagonal ~23.3 m)
    5  goal error lateral / diag
    6  distance / diag
    7  prev vx (norm)
    8  prev vy (norm)
    9  prev vyaw (norm)

Slots 0,1,4,5,6 are scaled by THIS arena's dimensions — the reason the policy
does not transfer to a differently-sized building without retraining.

## Eval results at snapshot
- Final model: 100% arrival across all 8 zones (randomised starts)
- best_model:  ~98% arrival

## How to reload
```python
from stable_baselines3 import PPO
model = PPO.load("nav_ppo_final.zip")   # needs the 10-D env.py in this folder
```

## Known limitation (motivates v2)
Wiggly / curved trajectories: weak action-smoothness penalty (0.02) and an
unpenalised lateral-strafe action let the policy "crab" and oscillate. v2
addresses both via reward shaping, alongside the layout-agnostic obs.
