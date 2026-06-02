# =============================================================================
# Cyber-Physical Security System – Dev Container
# Ubuntu 22.04 + Python 3.10 + RL stack + Webots R2025a
# GPU-agnostic: works on NVIDIA, AMD, or CPU-only machines.
# PyTorch bundles its own CUDA runtime — no nvidia/cuda base needed.
# =============================================================================
FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG WEBOTS_VERSION=R2025a

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl git ca-certificates gnupg lsb-release software-properties-common \
    python3 python3-venv python3-dev python3-pip \
    build-essential gcc g++ \
    xvfb x11vnc novnc websockify fluxbox \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender1 \
    libavcodec-extra libglu1-mesa libxkbcommon-x11-0 libxcb-keysyms1 \
    libxcb-image0 libxcb-icccm4 libxcb-randr0 libxcb-render-util0 \
    libxcb-xinerama0 libxcb-xfixes0 libxdamage1 libxcomposite1 \
    libxtst6 libnss3 libasound2 libpulse0 \
    # Webots dependencies
    libatk1.0-0 ffmpeg libfreeimage3 libegl1 libgtk-3-0 \
    libssh-dev libzip-dev xserver-xorg-core libxslt1.1 libxcb-cursor0 \
    vim nano htop tmux \
    && rm -rf /var/lib/apt/lists/*

# ── Install Webots ───────────────────────────────────────────────────────────
RUN apt-get update \
    && wget -qO /tmp/webots.deb \
       "https://github.com/cyberbotics/webots/releases/download/${WEBOTS_VERSION}/webots_2025a_amd64.deb" \
    && apt-get install -y -f /tmp/webots.deb \
    && rm /tmp/webots.deb \
    && rm -rf /var/lib/apt/lists/*

ENV WEBOTS_HOME=/usr/local/webots
ENV PATH="${WEBOTS_HOME}:${PATH}"
ENV LD_LIBRARY_PATH="${WEBOTS_HOME}/lib/controller:${LD_LIBRARY_PATH}"

# ── Python environment ───────────────────────────────────────────────────────
RUN ln -sf /usr/bin/python3 /usr/bin/python

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# ── Workspace ────────────────────────────────────────────────────────────────
WORKDIR /workspace
RUN mkdir -p /workspace/data/logs

# ── VNC / noVNC for remote GUI access ────────────────────────────────────────
ENV DISPLAY=:99
EXPOSE 6080 8888

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
