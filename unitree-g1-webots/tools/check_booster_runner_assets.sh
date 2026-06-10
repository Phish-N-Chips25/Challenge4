#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/external/booster_runner"
WEBOTS_ZIP="${ARTIFACT_DIR}/webots_simulation.zip"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

resolve_runner() {
  local runner

  if [[ -n "${BOOSTER_RUNNER_PATH:-}" ]]; then
    printf '%s\n' "${BOOSTER_RUNNER_PATH}"
    return
  fi

  runner="$(find "${ARTIFACT_DIR}" -maxdepth 1 -type f \
    \( -name 'booster-runner-webots-full-*.run' -o -name 'booster-runner-full-*.run' \) \
    ! -name '*7dof*' \
    | sort \
    | tail -n 1)"

  if [[ -n "${runner}" ]]; then
    printf '%s\n' "${runner}"
    return
  fi

  printf '%s\n' "${ARTIFACT_DIR}/booster-runner-full-0.0.10.run"
}

require_file() {
  local path="$1"
  [[ ! -L "${path}" ]] || fail "${path} must not be a symlink"
  [[ -f "${path}" ]] || fail "missing ${path}"
}

require_min_size() {
  local path="$1"
  local min_bytes="$2"
  local size
  size="$(wc -c < "${path}" | tr -d ' ')"
  [[ "${size}" -ge "${min_bytes}" ]] || fail "${path} is too small: ${size} bytes"
  printf '%s: %s bytes\n' "${path}" "${size}"
}

RUNNER="$(resolve_runner)"

require_file "${RUNNER}"
require_file "${WEBOTS_ZIP}"

require_min_size "${RUNNER}" 90000000
require_min_size "${WEBOTS_ZIP}" 4000000

if [[ ! -x "${RUNNER}" ]]; then
  chmod +x "${RUNNER}"
fi

if command -v file >/dev/null 2>&1; then
  file "${RUNNER}"
  file "${WEBOTS_ZIP}"
fi

if command -v unzip >/dev/null 2>&1; then
  if ! unzip -tq "${WEBOTS_ZIP}" >/dev/null; then
    fail "zip integrity failed for ${WEBOTS_ZIP}"
  fi
  printf 'zip integrity: OK\n'
else
  printf 'zip integrity: SKIPPED, unzip not installed\n'
fi

printf 'Booster runner assets are present and plausible.\n'
