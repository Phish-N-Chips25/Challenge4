# Cyber-Physical Security System

RL-trained robot patrol in a simulated office with cameras and motion sensors.

## Prerequisites

- **Docker** ≥ 24.0 + **Docker Compose** v2
- **NVIDIA GPU users only**: NVIDIA drivers + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

## Quick start

```bash
# 1. Clone the repo
git clone <repo-url> && cd Challenge4

# 2. Build (one image, ~8-10 GB, only needed once)
docker compose build train

# 3a. WITHOUT a GPU (works on any machine)
docker compose run --rm train

# 3b. WITH an NVIDIA GPU (training ~5x faster)
docker compose --profile gpu run --rm train-gpu

# 4. GUI mode (Webots in browser at http://localhost:6080)
docker compose up gui                     # CPU
docker compose --profile gpu up gui-gpu   # GPU
```

### Verify GPU inside the container

```bash
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

This will print `True` if you used the gpu profile and have
a working NVIDIA setup, `False` otherwise. Both are fine —
training just runs slower on CPU.

## Project structure

```
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── configs/
│   └── ppo.yaml                    # RL hyperparameters & env config
├── scripts/
│   └── entrypoint.sh
├── src/
│   ├── webots_world/               # .wbt world file + protos
│   ├── controllers/
│   │   └── patrol_robot/           # Webots robot controller
│   ├── rl/                         # Gymnasium env wrapper + training
│   ├── detection/                  # Face detection model + inference
│   └── utils/                      # Metrics, logging, shared helpers
└── data/
    ├── models/                     # Saved weights (git-ignored)
    ├── logs/                       # TensorBoard logs (git-ignored)
    └── results/                    # Eval CSVs and plots
```

## Common tasks

```bash
# Train the RL agent (GPU)
docker compose --profile gpu run --rm train-gpu \
    python src/rl/train.py --config configs/ppo.yaml

# Train the RL agent (CPU)
docker compose run --rm train \
    python src/rl/train.py --config configs/ppo.yaml

# Run Webots headless (faster training)
docker compose run --rm train \
    webots --mode=fast --no-rendering --minimize /workspace/src/webots_world/office.wbt

# TensorBoard only
docker compose run --rm -p 8888:8888 train \
    tensorboard --logdir /workspace/data/logs --port 8888 --bind_all
```

## Notes

- The `/workspace` volume mount means you edit code on your host
  with your normal editor — changes appear inside the container instantly.
  No rebuild needed after code changes.
- Rebuild only when `requirements.txt` or `Dockerfile` changes.
- PyTorch bundles its own CUDA runtime, so no nvidia/cuda base
  image is needed. GPU users just need host NVIDIA drivers +
  NVIDIA Container Toolkit.
