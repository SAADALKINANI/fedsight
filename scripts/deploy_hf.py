"""Deploy FedSight to a free Hugging Face Space (Docker SDK).

Usage:
    export HF_TOKEN=hf_...            # a token with "write" access, from huggingface.co/settings/tokens
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/deploy_hf.py --space YOUR_HF_USERNAME/fedsight

The Space gets its own README (it needs a YAML header that would look odd on GitHub), the files the
Dockerfile copies, and the API key as a Space secret, so the key never lands in a repo or an image.
Hugging Face then builds the Dockerfile itself, which means nothing has to be built on your machine.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ["Dockerfile", "requirements.txt", "LICENSE", "fedsight", "web", "data", "evals/results"]

SPACE_README = """---
title: FedSight
emoji: 📑
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8080
pinned: false
license: mit
short_description: Cited answers from GAO, FEMA and CDC sources
---

# FedSight

A research assistant that answers questions about GAO reports, FEMA rules and CDC data, with a
citation for every claim and a check that each quoted passage really appears in the sources.

Source code, evaluation results and design notes: https://github.com/SAADALKINANI/fedsight
"""


def stage(dest: Path) -> None:
    for item in INCLUDE:
        src = ROOT / item
        if not src.exists():
            sys.exit(f"missing {item}; run the build scripts first")
        target = dest / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, target)
    (dest / "README.md").write_text(SPACE_README, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", required=True, help="owner/name of the Space, e.g. jdoe/fedsight")
    ap.add_argument("--rate-limit", default="15", help="questions per visitor per hour")
    ap.add_argument("--daily-cap", default="200", help="questions per day across all visitors")
    args = ap.parse_args()

    token, key = os.getenv("HF_TOKEN"), os.getenv("ANTHROPIC_API_KEY")
    if not token or not key:
        sys.exit("set HF_TOKEN and ANTHROPIC_API_KEY first")

    api = HfApi(token=token)
    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    api.add_space_secret(args.space, "ANTHROPIC_API_KEY", key)
    api.add_space_variable(args.space, "FEDSIGHT_RATE_LIMIT", args.rate_limit)
    api.add_space_variable(args.space, "FEDSIGHT_DAILY_CAP", args.daily_cap)

    with tempfile.TemporaryDirectory() as tmp:
        stage(Path(tmp))
        api.upload_folder(folder_path=tmp, repo_id=args.space, repo_type="space",
                          commit_message="Deploy FedSight")
    print("uploaded; waiting for the build (the first one takes several minutes)")

    for _ in range(120):
        stage_name = api.get_space_runtime(args.space).stage
        print("  stage:", stage_name)
        if stage_name in ("RUNNING", "BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
            break
        time.sleep(15)

    owner, name = args.space.split("/")
    print(f"\nSpace page: https://huggingface.co/spaces/{args.space}")
    print(f"Live app:   https://{owner.lower()}-{name.lower().replace('_', '-')}.hf.space")


if __name__ == "__main__":
    main()
