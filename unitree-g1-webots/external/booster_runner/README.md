# Booster T1 Webots Runner Artifacts

This directory is for Booster-provided simulation artifacts from the official T1 manual.

Do not commit the downloaded `.run` or `.zip` files. They are vendor binaries and are ignored by `.gitignore`.

## Required files

Place these files here:

- `booster-runner-webots-full-0.0.11.run` or `booster-runner-full-0.0.10.run`
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

Newer Booster downloads may use a filename like `booster-runner-webots-full-0.0.11.run`. The project tools automatically select the non-7DOF Webots runner and ignore the separate `*7dof*` runner unless `BOOSTER_RUNNER_PATH` is set explicitly.

After placing the files here, run:

```bash
./tools/check_booster_runner_assets.sh
```
