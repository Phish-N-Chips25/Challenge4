# Booster T1 Webots Runner Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acquire Booster's official T1 Webots simulation runner package, store it outside git, validate it locally, and use it to expose the Booster high-level movement runtime required by `/booster_rpc_service` and SDK walking examples.

**Architecture:** The project keeps Booster-provided binaries in `external/booster_runner/`, ignored by git, with small committed scripts that validate and start the package. Existing ROS 2 movement code remains unchanged; the runner is treated as the missing vendor runtime that must be started before the ROS2 RPC client or C++ SDK walking client can move the simulated robot.

**Tech Stack:** macOS host, Ubuntu 22.04-compatible Booster `.run` package, Webots, Apple Container, ROS 2 Humble, Bash, Booster Robotics SDK.

---

## Source Facts

- Official Booster open-source page: https://www.booster.tech/open-source/
- Official T1 manual page referenced by Booster: https://booster.feishu.cn/wiki/DtFgwVXYxiBT8BksUPjcOwG4n4f
- Public mirror of the T1 manual: https://manuals.plus/m/00692b3719908055cd9ad4fb538b64d0e82668a893ec4f86dae52306b9e03f0b
- Manual-required Webots files:
  - `webots_simulation.zip`, expected displayed size `4.47MB`
  - `booster-runner-full-0.0.10.run`, expected displayed size `96.60MB`
- Manual runner command:

```bash
./booster-runner-full-0.0.x.run webots
```

- Manual SDK movement smoke command:

```bash
./b1_loco_example_client 127.0.0.1
```

- Manual walking inputs inside the SDK example:

```text
mw
w
l
```

## File Structure

- Create `external/booster_runner/README.md`: explains exactly which Booster artifacts to download, where to place them, and why the binaries are not committed.
- Modify `.gitignore`: ignore downloaded Booster runner artifacts while allowing the directory README.
- Create `tools/check_booster_runner_assets.sh`: verifies that `webots_simulation.zip` and `booster-runner-full-0.0.10.run` exist, have plausible sizes, and the runner is executable.
- Create `tools/start_booster_webots_runner.sh`: starts the official runner from `external/booster_runner/`, writes logs and PID files, and refuses to start when validation fails.
- Modify `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`: documents the official runner acquisition flow and the exact movement smoke test.

## Task 1: Artifact Directory And Git Ignore

**Files:**
- Create: `external/booster_runner/README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Add artifact ignore rules**

Append this block to `.gitignore`:

```gitignore
# Booster official simulation runner artifacts.
# These are vendor binaries downloaded from Booster's Feishu/manual resources.
external/booster_runner/*
!external/booster_runner/README.md
```

- [ ] **Step 2: Create the artifact README**

Create `external/booster_runner/README.md` with this content:

````markdown
# Booster T1 Webots Runner Artifacts

This directory is for Booster-provided simulation artifacts from the official T1 manual.

Do not commit the downloaded `.run` or `.zip` files. They are vendor binaries and are ignored by `.gitignore`.

## Required files

Place these files here:

- `booster-runner-full-0.0.10.run`
- `webots_simulation.zip`

Official source trail:

1. Open https://www.booster.tech/open-source/
2. Open the `T1 Manual` link.
3. In the Feishu T1 manual, find `Development in Webots Simulation Environment`.
4. Download `webots_simulation.zip`.
5. Download `booster-runner-full-0.0.10.run`.

Public manual mirror for confirming filenames and sizes:

- https://manuals.plus/m/00692b3719908055cd9ad4fb538b64d0e82668a893ec4f86dae52306b9e03f0b

Expected displayed sizes in the manual:

- `webots_simulation.zip`: `4.47MB`
- `booster-runner-full-0.0.10.run`: `96.60MB`

After placing the files here, run:

```bash
./tools/check_booster_runner_assets.sh
```
````

- [ ] **Step 3: Verify ignore behavior**

Run:

```bash
git status --short
```

Expected: `external/booster_runner/README.md` appears as untracked or staged, but downloaded `.run` and `.zip` files do not appear.

- [ ] **Step 4: Commit**

Run:

```bash
git add .gitignore external/booster_runner/README.md
git commit -m "docs(booster): add runner artifact location"
```

Expected: commit succeeds.

## Task 2: Asset Validator

**Files:**
- Create: `tools/check_booster_runner_assets.sh`

- [ ] **Step 1: Create the validator script**

Create `tools/check_booster_runner_assets.sh` with this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/external/booster_runner"
RUNNER="${ARTIFACT_DIR}/booster-runner-full-0.0.10.run"
WEBOTS_ZIP="${ARTIFACT_DIR}/webots_simulation.zip"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  local path="$1"
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
  unzip -tq "${WEBOTS_ZIP}" >/dev/null
  printf 'zip integrity: OK\n'
else
  printf 'zip integrity: SKIPPED, unzip not installed\n'
fi

printf 'Booster runner assets are present and plausible.\n'
```

- [ ] **Step 2: Make the validator executable**

Run:

```bash
chmod +x tools/check_booster_runner_assets.sh
```

Expected: command exits with status `0`.

- [ ] **Step 3: Run the validator before downloads**

Run:

```bash
./tools/check_booster_runner_assets.sh
```

Expected: fails with:

```text
ERROR: missing /Users/rynalde/Documents/ISEP-Challenge-Robotics/external/booster_runner/booster-runner-full-0.0.10.run
```

- [ ] **Step 4: Commit**

Run:

```bash
git add tools/check_booster_runner_assets.sh
git commit -m "chore(booster): add runner asset validator"
```

Expected: commit succeeds.

## Task 3: Download Official Booster Files

**Files:**
- Download to: `external/booster_runner/booster-runner-full-0.0.10.run`
- Download to: `external/booster_runner/webots_simulation.zip`

- [ ] **Step 1: Open official Booster source page**

Run:

```bash
open 'https://www.booster.tech/open-source/'
```

Expected: browser opens Booster's official open-source page.

- [ ] **Step 2: Open the T1 manual**

On the official open-source page, open `T1 Manual`.

Expected: Feishu opens the T1 manual page at:

```text
https://booster.feishu.cn/wiki/DtFgwVXYxiBT8BksUPjcOwG4n4f
```

- [ ] **Step 3: Download the Webots artifacts**

In the Feishu manual section `Development in Webots Simulation Environment`, download:

```text
webots_simulation.zip
booster-runner-full-0.0.10.run
```

Expected: the files exist in the browser downloads directory.

- [ ] **Step 4: Move downloads into the repo artifact directory**

Run, adjusting only the source directory if the browser used a different download folder:

```bash
mkdir -p external/booster_runner
mv ~/Downloads/webots_simulation.zip external/booster_runner/webots_simulation.zip
mv ~/Downloads/booster-runner-full-0.0.10.run external/booster_runner/booster-runner-full-0.0.10.run
```

Expected: both `mv` commands exit with status `0`.

- [ ] **Step 5: Validate the downloaded artifacts**

Run:

```bash
./tools/check_booster_runner_assets.sh
```

Expected output includes:

```text
zip integrity: OK
Booster runner assets are present and plausible.
```

- [ ] **Step 6: Verify downloaded binaries are not tracked**

Run:

```bash
git status --short external/booster_runner
```

Expected output:

```text
```

No `.run` or `.zip` file should appear.

## Task 4: Runner Start Script

**Files:**
- Create: `tools/start_booster_webots_runner.sh`

- [ ] **Step 1: Create the runner start script**

Create `tools/start_booster_webots_runner.sh` with this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/external/booster_runner"
RUNNER="${ARTIFACT_DIR}/booster-runner-full-0.0.10.run"
LOG_DIR="${ROOT_DIR}/.logs"
LOG_FILE="${LOG_DIR}/booster-webots-runner.log"
PID_FILE="${LOG_DIR}/booster-webots-runner.pid"

"${ROOT_DIR}/tools/check_booster_runner_assets.sh"

mkdir -p "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
  old_pid="$(cat "${PID_FILE}")"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" >/dev/null 2>&1; then
    printf 'Booster Webots runner already running with PID %s\n' "${old_pid}"
    printf 'Log: %s\n' "${LOG_FILE}"
    exit 0
  fi
fi

cd "${ARTIFACT_DIR}"
nohup "${RUNNER}" webots > "${LOG_FILE}" 2>&1 &
runner_pid="$!"
printf '%s\n' "${runner_pid}" > "${PID_FILE}"

printf 'Started Booster Webots runner with PID %s\n' "${runner_pid}"
printf 'Log: %s\n' "${LOG_FILE}"
```

- [ ] **Step 2: Make the start script executable**

Run:

```bash
chmod +x tools/start_booster_webots_runner.sh
```

Expected: command exits with status `0`.

- [ ] **Step 3: Run shell syntax checks**

Run:

```bash
bash -n tools/check_booster_runner_assets.sh
bash -n tools/start_booster_webots_runner.sh
```

Expected: both commands exit with status `0`.

- [ ] **Step 4: Commit**

Run:

```bash
git add tools/start_booster_webots_runner.sh
git commit -m "chore(booster): add Webots runner launcher"
```

Expected: commit succeeds.

## Task 5: Documentation Update

**Files:**
- Modify: `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`

- [ ] **Step 1: Add official runner setup section**

In `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`, add this section after `## How to start Webots`:

````markdown
## Official Booster T1 Webots runner

The high-level movement examples require Booster's official simulation control runner. The public ROS 2 SDK package provides interfaces and clients, but not the runtime that serves movement RPCs.

Download these files from the official T1 manual linked at https://www.booster.tech/open-source/:

- `webots_simulation.zip`
- `booster-runner-full-0.0.10.run`

Place both files in:

```bash
external/booster_runner
```

Validate them:

```bash
./tools/check_booster_runner_assets.sh
```

Start the official Webots runner:

```bash
./tools/start_booster_webots_runner.sh
```

The runner must stay open while testing walking commands.
````

- [ ] **Step 2: Add movement smoke test section**

In `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`, add this section after `## ROS 2 RPC movement client`:

````markdown
## Official runner walking smoke test

After the official Booster Webots runner is running, verify the SDK path first:

```bash
container exec --interactive booster-t1-ros bash -lc '
  cd /workspace/project/external/booster_robotics_sdk/build &&
  printf "mw\nw\nl\n" | timeout 15s ./b1_loco_example_client 127.0.0.1
'
```

Expected behavior:

- `mw` switches to walking mode.
- `w` commands forward walking.
- `l` stops walking.

Then verify the ROS 2 service exists:

```bash
container exec booster-t1-ros bash -lc '
  source /opt/ros/humble/setup.bash &&
  source /workspace/project/ros2_ws/install/setup.bash &&
  ros2 service list | grep booster_rpc_service
'
```

Expected output includes:

```text
/booster_rpc_service
```

Run the safe ROS 2 forward command:

```bash
container exec --interactive booster-t1-ros bash -lc '
  source /opt/ros/humble/setup.bash &&
  source /workspace/project/ros2_ws/install/setup.bash &&
  ros2 run booster_t1_webots_test rpc_movement_client --command forward --duration 0.5
'
```
````

- [ ] **Step 3: Commit**

Run:

```bash
git add docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md
git commit -m "docs(booster): document official Webots runner flow"
```

Expected: commit succeeds.

## Task 6: End-To-End Verification

**Files:**
- Read: `external/booster_runner/booster-runner-full-0.0.10.run`
- Read: `external/booster_runner/webots_simulation.zip`
- Read: `.logs/booster-webots-runner.log`

- [ ] **Step 1: Build the ROS workspace**

Run:

```bash
container exec booster-t1-ros bash -lc '
  cd /workspace/project/ros2_ws &&
  source /opt/ros/humble/setup.bash &&
  colcon build --symlink-install &&
  source install/setup.bash &&
  ros2 interface show booster_interface/srv/RpcService
'
```

Expected output includes:

```text
uint16 api_id
string request
---
uint16 api_id
uint16 error_code
string response
```

- [ ] **Step 2: Start the official runner**

Run:

```bash
./tools/start_booster_webots_runner.sh
```

Expected output includes:

```text
Started Booster Webots runner with PID
```

- [ ] **Step 3: Inspect runner logs**

Run:

```bash
tail -n 80 .logs/booster-webots-runner.log
```

Expected: no fatal startup error is present; Webots simulation/control runtime stays running.

- [ ] **Step 4: Run official SDK walking smoke test**

Run:

```bash
container exec --interactive booster-t1-ros bash -lc '
  cd /workspace/project/external/booster_robotics_sdk/build &&
  printf "mw\nw\nl\n" | timeout 15s ./b1_loco_example_client 127.0.0.1
'
```

Expected: the command does not print `RpcClient::WaitForService timed out`.

- [ ] **Step 5: Run ROS 2 forward walking smoke test**

Run:

```bash
container exec --interactive booster-t1-ros bash -lc '
  source /opt/ros/humble/setup.bash &&
  source /workspace/project/ros2_ws/install/setup.bash &&
  timeout 15s ros2 run booster_t1_webots_test rpc_movement_client --command forward --duration 0.5
'
```

Expected: the command exits without repeatedly printing `waiting for /booster_rpc_service`.

- [ ] **Step 6: Capture final git state**

Run:

```bash
git status --short
```

Expected: no downloaded `.run` or `.zip` artifacts appear. Only intentional source/docs changes should be committed.

## Self-Review

- Spec coverage: The plan covers getting the official Booster runner from the Feishu/manual resources, storing the vendor artifacts locally, validating them, starting the runner, and proving SDK/ROS2 walking works.
- Placeholder scan: The plan contains exact filenames, paths, commands, script contents, and expected outputs. It intentionally does not invent a direct Feishu `curl` URL because the official resource may require browser/authenticated Feishu access.
- Type consistency: Script paths, artifact names, and docs references consistently use `external/booster_runner`, `booster-runner-full-0.0.10.run`, and `webots_simulation.zip`.
