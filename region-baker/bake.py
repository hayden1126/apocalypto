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
# Pinned like the planet build: a rebake must reproduce the same bytes under one package_version.
ASSETS_SHA = "028c18f713baecad011301ff7a69acc39bcc2ae7"
ASSETS_URL = f"https://codeload.github.com/protomaps/basemaps-assets/tar.gz/{ASSETS_SHA}"
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
    expected = f"{region['id']}@{region['version']}"
    if region["package_version"] != expected:
        sys.exit(f"package_version {region['package_version']!r} != {expected!r} (id@version): bump both together")
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


def cmd_clean(region: dict, region_path: Path) -> None:
    """Delete the package dir so a full bake starts clean (stale files cannot enter the manifest)."""
    dest = out_dir(region)
    if dest.exists():
        shutil.rmtree(dest)
        print(f"cleaned {dest}")


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
    """Download (once, cached) and unpack the pinned basemaps-assets tree; return its root."""
    cache = BAKER_DIR / "cache"
    root = cache / f"basemaps-assets-{ASSETS_SHA}"
    if root.exists():
        return root
    cache.mkdir(exist_ok=True)
    print(f"+ fetch {ASSETS_URL}")
    with urllib.request.urlopen(ASSETS_URL) as resp:
        data = resp.read()
    tmp = cache / f".tmp-{ASSETS_SHA}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(tmp, filter="data")
    # publish atomically: an interrupted extract can never become the cache
    (tmp / root.name).rename(root)
    tmp.rmdir()
    return root


def fonts_in(value) -> set[str]:
    """Extract font-stack names from a text-font value (plain list or literal/case/match/step expression)."""
    if not isinstance(value, list) or not value:
        return set()
    if all(isinstance(v, str) for v in value) and value[0] != "literal":
        return set(value)
    op = value[0]
    if op == "literal" and len(value) == 2:
        return fonts_in(value[1])
    if op == "case":  # ["case", cond, out, ..., fallback]: outputs at 2, 4, ...; fallback last
        return _fonts_union(value[2:-1:2]) | fonts_in(value[-1])
    if op == "match":  # ["match", input, label, out, ..., fallback]: outputs at 3, 5, ...; fallback last
        return _fonts_union(value[3:-1:2]) | fonts_in(value[-1])
    if op == "step":  # ["step", input, out, stop, out, ...]: outputs at 2, 4, ...
        return _fonts_union(value[2::2])
    return set()


def _fonts_union(values) -> set[str]:
    """Union of fonts_in over a sequence of expression outputs."""
    stacks: set[str] = set()
    for v in values:
        stacks |= fonts_in(v)
    return stacks


def collect_fonts(node) -> set[str]:
    """Recursively collect font stacks from every text-font occurrence in a style node.

    Covers both layout["text-font"] and the {"text-font": ...} overrides inside
    text-field format expressions, wherever they nest.
    """
    stacks: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            stacks |= fonts_in(value) if key == "text-font" else collect_fonts(value)
    elif isinstance(node, list):
        for value in node:
            stacks |= collect_fonts(value)
    return stacks


def cmd_assets(region: dict, region_path: Path) -> None:
    """Copy the style-referenced glyph stacks and the flavor sprites into the package."""
    dest = out_dir(region)
    style_path = dest / f"style.{region['flavor']}.json"
    if not style_path.exists():
        sys.exit("style not baked yet: run `bake.py style` first (assets are style-driven)")
    assets = fetch_assets()
    stacks = collect_fonts(json.loads(style_path.read_text()).get("layers", []))
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


def cmd_manifest(region: dict, region_path: Path) -> None:
    """Write the package manifest (schema, package_version, checksums) + its committed copy."""
    dest = out_dir(region)
    files = []
    for f in sorted(p for p in dest.rglob("*") if p.is_file()):
        rel = f.relative_to(dest).as_posix()
        if rel == "manifest.json":  # only the package-root manifest is excluded, never nested files
            continue
        files.append({
            "path": rel,
            "bytes": f.stat().st_size,
            "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
        })
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "package_version": region["package_version"],
        "id": region["id"],
        "version": region["version"],
        "name": region.get("name"),
        "bbox": region["bbox"],
        "maxzoom": region["maxzoom"],
        "flavor": region["flavor"],
        "lang": region["lang"],
        "planet": region["planet"],
        "assets_sha": ASSETS_SHA,
        "tiles": "region.pmtiles",
        "style": f"style.{region['flavor']}.json",
        "graph": None,
        "graph_crs": region.get("graph_crs"),
        "files": files,
    }
    text = json.dumps(manifest, indent=2) + "\n"
    (dest / "manifest.json").write_text(text)
    committed = BAKER_DIR / "manifests" / f"{region['id']}-{region['version']}.manifest.json"
    committed.parent.mkdir(exist_ok=True)
    committed.write_text(text)
    print(f"wrote {dest / 'manifest.json'} and {committed} ({len(files)} files)")


def main() -> None:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "clean", "tiles", "style", "assets", "manifest", "all"])
    parser.add_argument("--region", type=Path, default=BAKER_DIR / "regions" / "ma-ling.region.json")
    args = parser.parse_args()
    region = load_region(args.region)
    commands = {
        "check": [cmd_check],
        "clean": [cmd_clean],
        "tiles": [cmd_tiles],
        "style": [cmd_style],
        "assets": [cmd_assets],
        "manifest": [cmd_manifest],
        # one clean pass under one package_version; assets are style-driven, so style bakes first
        "all": [cmd_check, cmd_clean, cmd_tiles, cmd_style, cmd_assets, cmd_manifest],
    }
    for cmd in commands[args.command]:
        cmd(region, args.region)


if __name__ == "__main__":
    main()
