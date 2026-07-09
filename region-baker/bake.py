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


def cmd_style(region: dict, region_path: Path) -> None:
    """Generate the offline MapLibre style from the pinned basemaps flavor."""
    dest = out_dir(region)
    dest.mkdir(parents=True, exist_ok=True)
    style = dest / f"style.{region['flavor']}.json"
    run(["node", str(BAKER_DIR / "gen_style.mjs"), str(region_path), str(style)])


def fetch_assets() -> Path:
    """Download (once, cached) and unpack the basemaps-assets tree; return its root."""
    cache = BAKER_DIR / "cache"
    root = cache / "basemaps-assets-main"
    if root.exists():
        return root
    cache.mkdir(exist_ok=True)
    print(f"+ fetch {ASSETS_URL}")
    with urllib.request.urlopen(ASSETS_URL) as resp:
        data = resp.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(cache, filter="data")
    return root


def fonts_in(text_font) -> set[str]:
    """Extract font-stack names from a text-font value (plain array or literal expression)."""
    if not isinstance(text_font, list):
        return set()
    if all(isinstance(v, str) for v in text_font):
        return set(text_font)
    stacks: set[str] = set()
    for i, v in enumerate(text_font):
        if v == "literal" and i + 1 < len(text_font) and isinstance(text_font[i + 1], list):
            stacks |= {s for s in text_font[i + 1] if isinstance(s, str)}
    return stacks


def cmd_assets(region: dict, region_path: Path) -> None:
    """Copy the style-referenced glyph stacks and the flavor sprites into the package."""
    dest = out_dir(region)
    style_path = dest / f"style.{region['flavor']}.json"
    if not style_path.exists():
        sys.exit("style not baked yet: run `bake.py style` first (assets are style-driven)")
    assets = fetch_assets()
    stacks: set[str] = set()
    for layer in json.loads(style_path.read_text()).get("layers", []):
        stacks |= fonts_in(layer.get("layout", {}).get("text-font", []))
    if not stacks:
        sys.exit("no text-font references in the style; refusing to bake a label-less package")
    for stack in sorted(stacks):
        src = assets / "fonts" / stack
        if not src.is_dir():
            sys.exit(f"font stack {stack!r} referenced by the style is missing from basemaps-assets")
        shutil.copytree(src, dest / "glyphs" / stack, dirs_exist_ok=True)
        print(f"glyphs: {stack} ({len(list((dest / 'glyphs' / stack).iterdir()))} ranges)")
    flavor = region["flavor"]
    copied = 0
    for f in sorted((assets / "sprites" / "v4").iterdir()):
        if f.name.split(".")[0] in (flavor, f"{flavor}@2x"):
            shutil.copy2(f, dest / f"sprite.{f.name}")
            copied += 1
    if copied != 4:
        sys.exit(f"expected 4 sprite files for flavor {flavor!r}, copied {copied}")
    print(f"sprites: {copied} files (sprite.{flavor}*)")


def main() -> None:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "tiles", "style", "assets"])
    parser.add_argument("--region", type=Path, default=BAKER_DIR / "regions" / "ma-ling.region.json")
    args = parser.parse_args()
    region = load_region(args.region)
    commands = {
        "check": [cmd_check],
        "tiles": [cmd_tiles],
        "style": [cmd_style],
        "assets": [cmd_assets],
    }
    for cmd in commands[args.command]:
        cmd(region, args.region)


if __name__ == "__main__":
    main()
