#!/usr/bin/env python3
"""Offline gate for a baked region package: integrity, local-only references, checksums, version match."""
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

from bake import MANIFEST_SCHEMA, fonts_in, pmtiles_bin

FAILURES: list[str] = []
CJK_RANGE = "19968-20223"  # first CJK Unified Ideographs block: proves CJK glyphs shipped


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record and print one check result."""
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def centroid_tile(bbox: list[float], z: int) -> tuple[int, int]:
    """Slippy x/y of the bbox centroid at zoom z."""
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def main() -> None:
    """Verify one package directory; exit 0 only if every check passes."""
    if len(sys.argv) != 2:
        sys.exit("usage: verify_package.py <package_dir>")
    pkg = Path(sys.argv[1]).resolve()

    manifest_path = pkg / "manifest.json"
    check("manifest present", manifest_path.is_file())
    if FAILURES:
        sys.exit(1)
    manifest = json.loads(manifest_path.read_text())
    check("manifest schema", manifest.get("schema") == MANIFEST_SCHEMA, str(manifest.get("schema")))

    # checksums + exact file-set match (no strays, nothing missing)
    disk = {p.relative_to(pkg).as_posix() for p in pkg.rglob("*") if p.is_file() and p.name != "manifest.json"}
    listed = {f["path"] for f in manifest["files"]}
    check("file set matches manifest", disk == listed,
          f"{len(disk)} on disk / {len(listed)} listed" + (f"; diff {sorted(disk ^ listed)[:4]}" if disk != listed else ""))
    bad = [f["path"] for f in manifest["files"]
           if not (pkg / f["path"]).is_file()
           or (pkg / f["path"]).stat().st_size != f["bytes"]
           or hashlib.sha256((pkg / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
    check("checksums", not bad, f"{len(manifest['files'])} files" + (f"; bad {bad[:4]}" if bad else ""))

    # archive integrity + a decodable centroid tile
    tiles = pkg / manifest["tiles"]
    verify = subprocess.run([pmtiles_bin(), "verify", str(tiles)], capture_output=True, text=True)
    check("pmtiles verify", verify.returncode == 0, (verify.stdout + verify.stderr).strip()[:120])
    x, y = centroid_tile(manifest["bbox"], manifest["maxzoom"])
    tile = subprocess.run([pmtiles_bin(), "tile", str(tiles), str(manifest["maxzoom"]), str(x), str(y)],
                          capture_output=True)
    check("centroid tile decodes", tile.returncode == 0 and len(tile.stdout) > 0,
          f"z{manifest['maxzoom']} {x}/{y}: {len(tile.stdout)} bytes")

    # style: offline-only references, all resolving inside the package
    style_path = pkg / manifest["style"]
    raw = style_path.read_text()
    check("style has no http references", "http://" not in raw and "https://" not in raw)
    style = json.loads(raw)
    for name, src in style.get("sources", {}).items():
        url = src.get("url", "")
        ok = url.startswith("pmtiles://") and (pkg / url.removeprefix("pmtiles://")).is_file()
        check(f"source {name} resolves locally", ok, url)
    sprite = style.get("sprite", "")
    missing_sprites = [s for s in (f"{sprite}.json", f"{sprite}.png", f"{sprite}@2x.json", f"{sprite}@2x.png")
                       if not (pkg / s).is_file()]
    check("sprite files resolve", sprite != "" and not missing_sprites, str(missing_sprites or sprite))
    stacks: set[str] = set()
    for layer in style.get("layers", []):
        stacks |= fonts_in(layer.get("layout", {}).get("text-font", []))
    check("style references glyph stacks", bool(stacks), f"{len(stacks)} stacks")
    for stack in sorted(stacks):
        for rng in ("0-255", CJK_RANGE):
            check(f"glyphs {stack} {rng}", (pkg / "glyphs" / stack / f"{rng}.pbf").is_file())

    # the Risk-3 contract: style and manifest carry the SAME package_version
    check("package_version match (Risk 3)",
          style.get("metadata", {}).get("apoc:package_version") == manifest["package_version"],
          f"style={style.get('metadata', {}).get('apoc:package_version')} manifest={manifest['package_version']}")

    if FAILURES:
        print(f"\nFAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print(f"\nALL PASS ({manifest['package_version']})")


if __name__ == "__main__":
    main()
