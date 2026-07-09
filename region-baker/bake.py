#!/usr/bin/env python3
"""Bake one versioned offline region package: PMTiles + dark style + local glyphs/sprites + manifest."""
import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

BAKER_DIR = Path(__file__).resolve().parent
ASSETS_URL = "https://codeload.github.com/protomaps/basemaps-assets/tar.gz/refs/heads/main"
MANIFEST_SCHEMA = "apoc.region-package/1"
REGION_KEYS = {"id", "version", "package_version", "bbox", "maxzoom", "planet", "flavor", "lang"}


def pmtiles_bin() -> str:
    """Locate the pmtiles CLI (PATH, then `~/go/bin`; `go install` names the binary go-pmtiles)."""
    for name in ("pmtiles", "go-pmtiles"):
        found = shutil.which(name) or (
            str(Path.home() / "go" / "bin" / name)
            if (Path.home() / "go" / "bin" / name).exists()
            else None
        )
        if found:
            return found
    sys.exit("pmtiles CLI not found: run `go install github.com/protomaps/go-pmtiles@latest`")


def load_region(path: Path) -> dict:
    """Load and sanity-check a region config."""
    region = json.loads(path.read_text())
    missing = REGION_KEYS - region.keys()
    if missing:
        sys.exit(f"region config {path} is missing keys: {sorted(missing)}")
    return region


def out_dir(region: dict) -> Path:
    """The package directory for a region config."""
    return BAKER_DIR / "out" / region["id"] / str(region["version"])


def run(cmd: list[str]) -> None:
    """Run a subprocess, failing loud."""
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def cmd_check(region: dict, region_path: Path) -> None:
    """Assert the bake toolchain is present and pinned."""
    print(f"PASS region config: {region_path} ({region['package_version']})")
    print(f"PASS pmtiles: {pmtiles_bin()}")
    node = shutil.which("node")
    if not node:
        sys.exit("FAIL node not found")
    print(f"PASS node: {node}")
    pinned = json.loads((BAKER_DIR / "package.json").read_text())["dependencies"]["@protomaps/basemaps"]
    installed_pkg = BAKER_DIR / "node_modules" / "@protomaps" / "basemaps" / "package.json"
    if not installed_pkg.exists():
        sys.exit("FAIL @protomaps/basemaps not installed: run `npm install` in region-baker/")
    installed = json.loads(installed_pkg.read_text())["version"]
    if installed != pinned:
        sys.exit(f"FAIL @protomaps/basemaps installed {installed} != pinned {pinned}")
    print(f"PASS @protomaps/basemaps {installed} (pinned {pinned})")


def cmd_tiles(region: dict, region_path: Path) -> None:
    """Range-extract the region bbox from the pinned planet build and verify the archive."""
    dest = out_dir(region)
    dest.mkdir(parents=True, exist_ok=True)
    tiles = dest / "region.pmtiles"
    bbox = ",".join(str(v) for v in region["bbox"])
    run([pmtiles_bin(), "extract", region["planet"], str(tiles),
         f"--bbox={bbox}", f"--maxzoom={region['maxzoom']}"])
    run([pmtiles_bin(), "verify", str(tiles)])
    print(f"wrote {tiles} ({tiles.stat().st_size} bytes)")


def main() -> None:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "tiles"])
    parser.add_argument("--region", type=Path, default=BAKER_DIR / "regions" / "ma-ling.region.json")
    args = parser.parse_args()
    region = load_region(args.region)
    commands = {"check": [cmd_check], "tiles": [cmd_tiles]}
    for cmd in commands[args.command]:
        cmd(region, args.region)


if __name__ == "__main__":
    main()
