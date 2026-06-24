#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# install_booster_opt.sh — populate the container's /opt/booster layout that the
# Booster runtime loads from HARD-CODED paths.
#
# This is the missing first-run step the vendor normally performs with
# `copy_robot_config.sh`, which is NOT shipped inside the self-extracting Webots
# runner (booster-runner-webots-full-*.run). Without it the runner logs
# `motion_state_publisher.cpp:68 Load robot config file failed` and the robot
# stands still while RPC calls still return status=0.
#
# What the runtime requires (verified with `strings mck` / the .so modules):
#   /opt/booster/configs/robot_config.yaml           (motion_state_publisher)
#   /opt/booster/configs/system_settings_config.yaml (mck / libmodule_source)
#   /opt/booster/robot_info.txt, /opt/booster/version.txt
#   /opt/booster/Gait/configs/, /opt/booster/Storage/
#
# mck copies these from a per-robot, version-keyed vendor config repo:
#   ../../booster_config/booster_configs/Booster_T1/T1_2.3.4/robot_config.yaml
#
# You must obtain that repo from Booster and drop it at ONE of:
#   external/booster_runner/booster_config/   (the booster_config repo)
#   external/booster_runner/opt_booster/      (a prebuilt /opt/booster tree)
# or point BOOSTER_OPT_SRC at it. Then run this script.
# ─────────────────────────────────────────────────────────────────────────────

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "${ROOT_DIR}/containers/docker_common.sh"
load_project_env "$(detect_platform)"

ARTIFACT_DIR="${ROOT_DIR}/external/booster_runner"
STAGE_DIR="${ROOT_DIR}/.docker/opt_booster"
CONTAINER_NAME="${CONTAINER_NAME:-booster-t1-ros}"
BOOSTER_MODEL="${BOOSTER_MODEL:-Booster_T1}"
BOOSTER_VERSION="${BOOSTER_VERSION:-T1_2.3.4}"
BOOSTER_OPT_OPTIONAL="${BOOSTER_OPT_OPTIONAL:-0}"

usage_missing() {
  if [[ "${BOOSTER_OPT_OPTIONAL}" == "1" || "${BOOSTER_OPT_OPTIONAL}" == "true" ]]; then
    cat >&2 <<EOF
NOTE: Booster vendor /opt config was not found.

The default 0.0.10 Webots simulation can continue with its bundled simulation
defaults. The 0.0.11 runner and real robot deployments still require the
per-robot vendor config.
EOF
  else
    cat >&2 <<EOF
ERROR: Booster locomotion config not found — the T1 cannot walk without it.

The Booster Webots runner ships WITHOUT the per-robot calibration its motion
stack loads from hard-coded /opt/booster paths, and WITHOUT the vendor
copy_robot_config.sh that installs it.

Obtain the vendor config repo from Booster (per-robot, keyed by model+version)
and place it at ONE of:

  external/booster_runner/booster_config/booster_configs/${BOOSTER_MODEL}/${BOOSTER_VERSION}/
      robot_config.yaml
      system_settings_config.yaml
  external/booster_runner/opt_booster/        (a prebuilt /opt/booster tree)

or set BOOSTER_OPT_SRC to its location, then re-run:

  ./tools/install_booster_opt.sh

It installs into the container at:
  /opt/booster/configs/robot_config.yaml
  /opt/booster/configs/system_settings_config.yaml
EOF
  fi
  exit 1
}

# Locate a directory that holds both required config yaml files.
find_config_dir() {
  local root="$1"
  [[ -d "${root}" ]] || return 1

  local candidates=(
    "${root}/booster_configs/${BOOSTER_MODEL}/${BOOSTER_VERSION}"
    "${root}/configs"
    "${root}"
  )
  local d
  for d in "${candidates[@]}"; do
    if [[ -f "${d}/robot_config.yaml" && -f "${d}/system_settings_config.yaml" ]]; then
      printf '%s\n' "${d}"
      return 0
    fi
  done

  # Last resort: find robot_config.yaml anywhere and use its dir if the sibling
  # system settings file is alongside it.
  local found fd
  found="$(find "${root}" -name robot_config.yaml -print 2>/dev/null | head -n 1 || true)"
  if [[ -n "${found}" ]]; then
    fd="$(dirname "${found}")"
    if [[ -f "${fd}/system_settings_config.yaml" ]]; then
      printf '%s\n' "${fd}"
      return 0
    fi
  fi
  return 1
}

# ── Resolve the vendor source ────────────────────────────────────────────────
SRC_ROOTS=()
[[ -n "${BOOSTER_OPT_SRC:-}" ]] && SRC_ROOTS+=("${BOOSTER_OPT_SRC}")
SRC_ROOTS+=("${ARTIFACT_DIR}/opt_booster" "${ARTIFACT_DIR}/booster_config")

CONFIG_DIR=""
SRC_OPT_TREE=""
for root in "${SRC_ROOTS[@]}"; do
  # A prebuilt /opt/booster tree (has configs/ plus identifier/Gait files)?
  if [[ -f "${root}/configs/robot_config.yaml" \
        && -f "${root}/configs/system_settings_config.yaml" \
        && ( -e "${root}/robot_info.txt" || -d "${root}/Gait" ) ]]; then
    SRC_OPT_TREE="${root}"
    CONFIG_DIR="${root}/configs"
    break
  fi
  if CONFIG_DIR="$(find_config_dir "${root}")"; then
    break
  fi
  CONFIG_DIR=""
done

[[ -n "${CONFIG_DIR}" ]] || usage_missing

printf 'Using Booster config from: %s\n' "${CONFIG_DIR}"

# ── Stage the /opt/booster tree on the host (bind-mounted into the container) ──
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}/configs" "${STAGE_DIR}/Gait/configs" "${STAGE_DIR}/Storage"

if [[ -n "${SRC_OPT_TREE}" ]]; then
  cp -a "${SRC_OPT_TREE}/." "${STAGE_DIR}/"
  mkdir -p "${STAGE_DIR}/configs" "${STAGE_DIR}/Gait/configs" "${STAGE_DIR}/Storage"
else
  cp -a "${CONFIG_DIR}/robot_config.yaml" "${STAGE_DIR}/configs/robot_config.yaml"
  cp -a "${CONFIG_DIR}/system_settings_config.yaml" "${STAGE_DIR}/configs/system_settings_config.yaml"
  # Copy any extra yaml the vendor dir provides (calibration, gait, etc.).
  find "${CONFIG_DIR}" -maxdepth 1 -name '*.yaml' -exec cp -a {} "${STAGE_DIR}/configs/" \;
  if [[ -d "${CONFIG_DIR}/Gait" ]]; then
    cp -a "${CONFIG_DIR}/Gait/." "${STAGE_DIR}/Gait/"
  fi
fi

# robot_info.txt / version.txt are small identifier files the runtime reads to
# select the config; synthesize them from model+version if the vendor dir omits
# them (they carry no calibration, only the model/version string).
if [[ ! -f "${STAGE_DIR}/robot_info.txt" ]]; then
  if [[ -f "${CONFIG_DIR}/robot_info.txt" ]]; then
    cp -a "${CONFIG_DIR}/robot_info.txt" "${STAGE_DIR}/robot_info.txt"
  else
    printf '%s\n%s\n' "${BOOSTER_MODEL}" "${BOOSTER_VERSION}" > "${STAGE_DIR}/robot_info.txt"
  fi
fi
if [[ ! -f "${STAGE_DIR}/version.txt" ]]; then
  if [[ -f "${CONFIG_DIR}/version.txt" ]]; then
    cp -a "${CONFIG_DIR}/version.txt" "${STAGE_DIR}/version.txt"
  else
    printf '%s\n' "${BOOSTER_VERSION}" > "${STAGE_DIR}/version.txt"
  fi
fi

printf 'Staged /opt/booster tree at: %s\n' "${STAGE_DIR}"

# ── Sync into the container at /opt/booster (root-owned; needs uid 0) ─────────
if ! docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  printf 'WARNING: container %s not found; staged config only.\n' "${CONTAINER_NAME}" >&2
  printf 'Start it (./containers/run_ros_container.sh) and re-run this script.\n' >&2
  exit 0
fi
if ! container_is_running; then
  docker start "${CONTAINER_NAME}" >/dev/null
  sleep 2
fi

printf 'Installing into %s:/opt/booster ...\n' "${CONTAINER_NAME}"
docker exec -u 0:0 "${CONTAINER_NAME}" bash -lc '
  set -euo pipefail
  rm -rf /opt/booster
  mkdir -p /opt/booster
  cp -a /workspace/project/.docker/opt_booster/. /opt/booster/
  chmod -R a+rX /opt/booster
  chmod -R a+rwX /opt/booster/Storage
'
printf 'Booster /opt/booster config installed. The runner can now load robot_config.yaml.\n'
