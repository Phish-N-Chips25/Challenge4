"""
Consistency check: do configs/ppo.yaml's zone positions match the actual
office layout in the .wbt file?

Run this whenever the office world is edited. It independently parses the
zone-mark Solid nodes straight out of the .wbt (via wbt_parser.py) and
diffs them against what the RL config (and the already-trained model)
assumes. Catches silent drift if someone moves a room in Webots without
telling the RL side — a real failure mode in a multi-person project where
the office layout and the navigation config are maintained by different
people.

Usage:
    python check_map_sync.py
    python check_map_sync.py --wbt ../world/sentinelmas_office.wbt --config ../../configs/ppo.yaml
"""

import argparse
import sys

import yaml

from wbt_parser import parse_zone_marks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wbt", default="../world/sentinelmas_office.wbt")
    parser.add_argument("--config", default="../../configs/ppo.yaml")
    parser.add_argument("--tol", type=float, default=0.05,
                        help="Allowed position drift in metres before flagging (default 0.05)")
    args = parser.parse_args()

    wbt_zones = parse_zone_marks(args.wbt)
    with open(args.config) as f:
        cfg_zones = yaml.safe_load(f)["env"]["zone_pos"]

    print(f"Office file:  {args.wbt}  ({len(wbt_zones)} zone marks)")
    print(f"RL config:    {args.config}  ({len(cfg_zones)} zones)")
    print()

    problems = []

    missing_in_cfg = set(wbt_zones) - set(cfg_zones)
    missing_in_wbt = set(cfg_zones) - set(wbt_zones)
    for z in missing_in_cfg:
        problems.append(f"'{z}' exists in the office layout but not in ppo.yaml")
    for z in missing_in_wbt:
        problems.append(f"'{z}' exists in ppo.yaml but not in the office layout")

    for z in sorted(set(wbt_zones) & set(cfg_zones)):
        wx, wy = wbt_zones[z]
        cx, cy = cfg_zones[z]
        drift = ((wx - cx) ** 2 + (wy - cy) ** 2) ** 0.5
        status = "OK" if drift <= args.tol else "DRIFT"
        print(f"  {z:<14} wbt=({wx:6.2f},{wy:6.2f})  cfg=({cx:6.2f},{cy:6.2f})  "
              f"drift={drift:.3f}m  [{status}]")
        if drift > args.tol:
            problems.append(f"'{z}' moved {drift:.2f}m in the office layout "
                            f"but ppo.yaml wasn't updated")

    print()
    if problems:
        print(f"FAILED — {len(problems)} issue(s):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    else:
        print("OK — ppo.yaml matches the office layout exactly.")


if __name__ == "__main__":
    main()
