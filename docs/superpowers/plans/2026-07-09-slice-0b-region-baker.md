# Slice 0b Group B: `region-baker` + First Dark PMTiles Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `region-baker/`, the one off-phone baker of spec section 10, and bake the first versioned offline region package for the 2 km walk area (Ma Ling Path, Hong Kong): vector tiles (PMTiles), a generated dark MapLibre style, local glyphs and sprites, and a checksummed manifest carrying the `PackageVersion` that both future readers (renderer, matcher) must assert. An offline verifier is the increment's gate. This front-loads spec Risk 3 (two-reader map-package drift): the manifest==style version contract is established and machine-checked before the graph and the renderer exist.

**Architecture:** `bake.py` (Python 3.12, stdlib only) drives five idempotent subcommands under one region config: `check` (toolchain pinned and present), `tiles` (`pmtiles extract` range-requests only the bbox's tiles out of the pinned 136 GB Protomaps daily planet), `style` (`gen_style.mjs` renders the `@protomaps/basemaps@5.7.2` dark flavor into a style whose every reference is package-relative), `assets` (copies exactly the glyph stacks the generated style references, plus the flavor sprites, from the basemaps-assets tarball), and `manifest` (bytes + sha256 for every file, `apoc.region-package/1` schema, a reserved `graph: null` slot, and a committed text copy under `manifests/`). `verify_package.py` re-checks everything offline: archive integrity, centroid-tile decode, local-only references (sampled CJK glyph range included), checksums, and the Risk-3 `package_version` match between style metadata and manifest. Binaries under `out/`, `node_modules/`, and `cache/` are gitignored; baker source, region config, pinned lockfiles, and the manifest copy are committed (the repo's "protocol committed, data gitignored" pattern).

**One deliberate deviation from the foundations sketch:** `all` chains tiles -> **style -> assets** -> manifest (style before assets), so the generated style's actual `text-font` references drive which glyph stacks get copied. Hard-coding stack names would drift silently when the flavor changes; style-driven copying cannot.

**Tech Stack:** Python 3.12 (stdlib only), node 22 + `@protomaps/basemaps@5.7.2` (pinned, zero deps), `go-pmtiles` CLI (installed via `go install`), the Protomaps daily planet build (pinned by date), the `protomaps/basemaps-assets` tarball for glyphs/sprites.

> **Reconciliation note (2026-07-09, post-review):** this plan is the as-authored artifact; a 10-finding adversarial review after execution hardened the shipped code, so read the code for current truth. The load-bearing fix: the style references font stacks inside nested `case` expressions and inside `text-field` `format` overrides (140 of 153 occurrences), which the planned `fonts_in` missed, so the shipped package lacked `Noto Sans Devanagari Regular v1` while the verifier (sharing the extractor) said ALL PASS. The shipped `fonts_in` is a real expression walker (`literal`/`case`/`match`/`step`) and a new `collect_fonts` recurses whole layers. Further shipped hardening: `basemaps-assets` pinned to a commit SHA (recorded as `assets_sha` in the manifest); atomic assets-cache extraction; `all` = check + clean + bake (pin asserted, stale files impossible); `load_region` asserts `package_version == id@version`; the verifier cross-checks archive header bounds/maxzoom against the manifest, uses a case-insensitive network-reference check plus per-field relative-path checks, bails cleanly after a schema FAIL, and excludes only the package-root `manifest.json`. The code blocks below predate these fixes.

## Context: the bbox is confirmed against the real walk

Measured from the private `prototypes/pdr-benchmark/data/phone/ma_ling_2km/Location.csv` (1826 fixes, gitignored): lat `[22.40544, 22.40878]`, lon `[114.20511, 114.20789]`. The planned bbox `[114.18764, 22.39089, 114.22764, 22.42089]` contains the whole track with 1.3 to 2.0 km of margin on every side, so it is adopted as-is. The pinned planet build `https://build.protomaps.com/20260708.pmtiles` exists (HTTP 200, 136.6 GB, range requests supported).

## Global Constraints

- The `pmtiles` CLI installs to `~/go/bin` (off PATH): `bake.py` locates it via PATH first, then `~/go/bin/pmtiles`, so no shell exports are needed to run the baker.
- Network is used ONLY at bake time (planet extract, assets tarball, npm install). The baked package and `verify_package.py` are fully offline; the verifier greps the style for `http` and fails on any hit.
- Every style reference (tile source, glyphs, sprites) is package-relative; the offline readers resolve them against the package root. `pmtiles://region.pmtiles` is the tile-source convention.
- One baker, one pass, one `package_version` (`ma-ling@1` from the region config) stamped into BOTH the manifest and `style.metadata["apoc:package_version"]`. Readers fail loud on mismatch (spec Risk 3).
- The baked routing graph is deferred (no `apoc-map` reader exists to verify against): the manifest reserves `graph: null` and records `graph_crs: EPSG:32650` for the later baker (the osmnx/UTM machinery already lives in `prototypes/pdr-benchmark/pdr_bench/mapmatch/`).
- Python follows the house pattern: imports at top, one-line docstrings, stdlib only for these two scripts.
- Commit after every task (conventional commits). Do not push; the human pushes explicitly.

### Out of scope for this plan (later increments)

The MapLibre pixel render of the package (no renderer exists yet; no reliable GL on WSL2), the Flutter shell that reads it, the baked pedestrian graph and its `apoc-map` reader, multi-region support beyond the one config, and tile-diff/update tooling. Group A (`apoc-ffi`) is a separate plan and a separate PR.

---

### Task 1: Scaffold + region config + toolchain bootstrap (`bake.py check`)

Creates `region-baker/` with the region config, the pinned npm dependency, the baker CLI skeleton with its `check` subcommand, and installs the two external tools. Deliverable: `python3 region-baker/bake.py check` all-PASS.

**Files:**
- Create: `region-baker/bake.py`
- Create: `region-baker/regions/ma-ling.region.json`
- Create: `region-baker/package.json`
- Create: `region-baker/.gitignore`
- Create: `region-baker/README.md`
- Generated (committed): `region-baker/package-lock.json`

**Interfaces:**
- Produces: `bake.py <check|tiles|style|assets|manifest|all> [--region <path>]` CLI; `load_region`, `out_dir`, `run`, `pmtiles_bin` helpers reused by every later task; the region config schema (`id`, `version`, `package_version`, `name`, `bbox`, `maxzoom`, `planet`, `flavor`, `lang`, `graph_crs`).

- [ ] **Step 1: Region config and npm pin**

`region-baker/regions/ma-ling.region.json`:

```json
{
  "id": "ma-ling",
  "version": 1,
  "package_version": "ma-ling@1",
  "name": "Ma On Shan / Ma Ling Path, Hong Kong (2 km walk validation area)",
  "bbox": [114.18764, 22.39089, 114.22764, 22.42089],
  "maxzoom": 15,
  "planet": "https://build.protomaps.com/20260708.pmtiles",
  "flavor": "dark",
  "lang": "en",
  "graph_crs": "EPSG:32650"
}
```

`region-baker/package.json`:

```json
{
  "name": "region-baker",
  "private": true,
  "type": "module",
  "dependencies": {
    "@protomaps/basemaps": "5.7.2"
  }
}
```

`region-baker/.gitignore`:

```gitignore
/out/
/node_modules/
/cache/
```

`region-baker/README.md`:

```markdown
# region-baker

The one off-phone baker (spec section 10): takes a region config + the pinned
Protomaps planet build and emits one versioned offline package under
`out/<id>/<version>/`: vector tiles (PMTiles), a dark MapLibre style with
package-relative references only, local glyphs + sprites, and a checksummed
manifest carrying the `package_version` both readers must assert.

## Prerequisites

- `go install github.com/protomaps/go-pmtiles@latest` (found via PATH or `~/go/bin`)
- `npm install` in this directory (pins `@protomaps/basemaps`)

## Bake and verify

    python3 bake.py check          # toolchain present and pinned
    python3 bake.py all            # tiles -> style -> assets -> manifest, one pass
    python3 verify_package.py out/ma-ling/1

Network is used only at bake time. The package and the verifier are offline.
Binaries under `out/` are gitignored; the manifest copy under `manifests/` is
committed.
```

- [ ] **Step 2: The baker CLI skeleton with `check`**

`region-baker/bake.py`:

```python
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


def main() -> None:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--region", type=Path, default=BAKER_DIR / "regions" / "ma-ling.region.json")
    args = parser.parse_args()
    region = load_region(args.region)
    commands = {"check": [cmd_check]}
    for cmd in commands[args.command]:
        cmd(region, args.region)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Bootstrap the toolchain and run the gate**

Run: `export PATH="$HOME/go/bin:$PATH"; go install github.com/protomaps/go-pmtiles@latest` (uses `~/.local/bin/go`; prefix `export PATH="$HOME/.local/bin:$PATH"` if `go` is not found)
Run: `cd region-baker && npm install` (writes `package-lock.json` and `node_modules/`)
Run: `python3 region-baker/bake.py check`
Expected: four PASS lines (region config, pmtiles, node, `@protomaps/basemaps 5.7.2`), exit 0.

- [ ] **Step 4: Commit**

```bash
git add region-baker/bake.py region-baker/regions region-baker/package.json \
        region-baker/package-lock.json region-baker/.gitignore region-baker/README.md
git commit -m "feat(region-baker): scaffold baker CLI, region config, pinned toolchain"
```

---

### Task 2: Extract the dark-map tiles (`bake.py tiles`)

Range-extracts only the bbox's tiles from the pinned planet build into `out/ma-ling/1/region.pmtiles` and verifies the archive three ways: `pmtiles verify`, bounds/zoom shown by `pmtiles show`, and a decoded non-empty tile at the bbox centroid (catches an empty or mistargeted extract). Deliverable: `region.pmtiles` passing all three.

**Files:**
- Modify: `region-baker/bake.py` (add `cmd_tiles`; extend `commands`)

**Interfaces:**
- Produces: `cmd_tiles(region, region_path)`; `out/ma-ling/1/region.pmtiles`.

- [ ] **Step 1: Implement `cmd_tiles`**

Add to `region-baker/bake.py` (below `cmd_check`):

```python
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
```

Extend `main`'s parser choices to `["check", "tiles"]` and `commands` with `"tiles": [cmd_tiles]`.

- [ ] **Step 2: Bake and verify the extract**

Run: `python3 region-baker/bake.py tiles`
Expected: the extract streams (seconds; it moves only the bbox's tiles), `pmtiles verify` prints no errors, the file lands at `region-baker/out/ma-ling/1/region.pmtiles` (sub-MB to a few MB).

Run: `~/go/bin/pmtiles show region-baker/out/ma-ling/1/region.pmtiles`
Expected: bounds contain `[114.18764, 22.39089, 114.22764, 22.42089]`, max zoom 15, tile count > 0.

Run a centroid decode (z15 slippy tile of the bbox center):

```bash
python3 - <<'EOF'
import math, subprocess
lon, lat, z = (114.18764 + 114.22764) / 2, (22.39089 + 22.42089) / 2, 15
n = 2 ** z
x = int((lon + 180) / 360 * n)
y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
out = subprocess.run(["pmtiles", "tile", "region-baker/out/ma-ling/1/region.pmtiles", str(z), str(x), str(y)],
                     capture_output=True, check=True).stdout
print(f"z{z} {x}/{y}: {len(out)} bytes"); assert out, "empty centroid tile"
EOF
```

Expected: a non-zero byte count.

- [ ] **Step 3: Commit**

```bash
git add region-baker/bake.py
git commit -m "feat(region-baker): extract dark PMTiles for the ma-ling bbox"
```

---

### Task 3: Offline style + style-driven glyphs and sprites (`bake.py style`, `bake.py assets`)

Generates `style.dark.json` from the pinned `@protomaps/basemaps` dark flavor with package-relative references only, then copies exactly the glyph stacks the style references (full range set, CJK included, so Traditional-Chinese labels render) and the four dark sprite files from the basemaps-assets tarball. Deliverable: a style with zero `http` references whose every asset resolves locally.

**Files:**
- Create: `region-baker/gen_style.mjs`
- Modify: `region-baker/bake.py` (add `fetch_assets`, `fonts_in`, `cmd_style`, `cmd_assets`; extend `commands`)

**Interfaces:**
- Produces: `cmd_style` / `cmd_assets`; `out/ma-ling/1/style.dark.json`, `out/ma-ling/1/glyphs/<stack>/<range>.pbf`, `out/ma-ling/1/sprite.dark{,@2x}.{json,png}`.

- [ ] **Step 1: The style generator**

`region-baker/gen_style.mjs`:

```javascript
// Generate the offline MapLibre style for a baked region package.
// Every reference is package-relative; the offline reader resolves against the
// package root. The package_version stamp here is half of the Risk-3 contract
// (the manifest carries the other half; verify_package.py asserts they match).
// Usage: node gen_style.mjs <region.json> <out_style.json>
import { readFileSync, writeFileSync } from "node:fs";
import { layers, namedFlavor } from "@protomaps/basemaps";

const [regionPath, outPath] = process.argv.slice(2);
if (!regionPath || !outPath) {
  console.error("usage: node gen_style.mjs <region.json> <out_style.json>");
  process.exit(2);
}
const region = JSON.parse(readFileSync(regionPath, "utf8"));

const style = {
  version: 8,
  name: `apoc ${region.id} ${region.flavor}`,
  metadata: {
    "apoc:schema": "apoc.region-package/1",
    "apoc:package_version": region.package_version,
  },
  glyphs: "glyphs/{fontstack}/{range}.pbf",
  sprite: `sprite.${region.flavor}`,
  sources: {
    protomaps: {
      type: "vector",
      url: "pmtiles://region.pmtiles",
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: layers("protomaps", namedFlavor(region.flavor), { lang: region.lang }),
};
writeFileSync(outPath, JSON.stringify(style, null, 2) + "\n");
console.log(`wrote ${outPath}`);
```

- [ ] **Step 2: Implement `cmd_style` and `cmd_assets`**

Add to `region-baker/bake.py`:

```python
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
```

Extend `main`'s parser choices to `["check", "tiles", "style", "assets"]` and `commands` with `"style": [cmd_style]`, `"assets": [cmd_assets]`.

- [ ] **Step 3: Bake and verify the style is fully local**

Run: `python3 region-baker/bake.py style && python3 region-baker/bake.py assets`
Expected: `style.dark.json` written; each referenced stack copied with 256 ranges; 4 sprite files.

Run: `grep -c http region-baker/out/ma-ling/1/style.dark.json`
Expected: `0`.

Run: `ls region-baker/out/ma-ling/1/glyphs/ && ls region-baker/out/ma-ling/1/ | grep sprite`
Expected: the referenced Noto Sans stacks; `sprite.dark.json`, `sprite.dark.png`, `sprite.dark@2x.json`, `sprite.dark@2x.png`.

- [ ] **Step 4: Commit**

```bash
git add region-baker/bake.py region-baker/gen_style.mjs
git commit -m "feat(region-baker): offline style + style-driven glyphs and sprites"
```

---

### Task 4: Manifest + offline verifier + one-pass bake (`bake.py manifest`, `bake.py all`, `verify_package.py`)

Writes the `apoc.region-package/1` manifest (bytes + sha256 for every file, the `package_version`, the reserved `graph: null` slot) plus its committed text copy, wires `all` as the one-pass bake, and lands the offline gate `verify_package.py`. Deliverable: `python3 region-baker/verify_package.py out/ma-ling/1` all-PASS.

**Files:**
- Modify: `region-baker/bake.py` (add `cmd_manifest`; extend `commands` with `manifest` and `all`)
- Create: `region-baker/verify_package.py`
- Generated (committed): `region-baker/manifests/ma-ling-1.manifest.json`

**Interfaces:**
- Produces: the manifest schema consumed by every future package reader; `verify_package.py <package_dir>` exit-0 gate.

- [ ] **Step 1: Implement `cmd_manifest` and the `all` chain**

Add to `region-baker/bake.py`:

```python
def cmd_manifest(region: dict, region_path: Path) -> None:
    """Write the package manifest (schema, package_version, checksums) + its committed copy."""
    dest = out_dir(region)
    files = []
    for f in sorted(p for p in dest.rglob("*") if p.is_file() and p.name != "manifest.json"):
        files.append({
            "path": f.relative_to(dest).as_posix(),
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
```

Extend `main`'s parser choices to the full `["check", "tiles", "style", "assets", "manifest", "all"]` and `commands` with:

```python
        "manifest": [cmd_manifest],
        # one pass under one package_version; assets are style-driven, so style bakes first
        "all": [cmd_tiles, cmd_style, cmd_assets, cmd_manifest],
```

- [ ] **Step 2: The offline verifier**

`region-baker/verify_package.py`:

```python
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
```

- [ ] **Step 3: One-pass bake + gate**

Run: `python3 region-baker/bake.py manifest && python3 region-baker/verify_package.py region-baker/out/ma-ling/1`
Expected: ALL PASS.

Run the one-pass property (idempotent full rebake under one version):
`python3 region-baker/bake.py all && python3 region-baker/verify_package.py region-baker/out/ma-ling/1`
Expected: ALL PASS again.

- [ ] **Step 4: Commit**

```bash
git add region-baker/bake.py region-baker/verify_package.py region-baker/manifests
git commit -m "feat(region-baker): manifest with checksums + offline package verifier"
```

---

## Self-Review

**1. Spec coverage.** This is the Group B half of the slice-0b foundations plan: the one off-phone baker (spec section 10) emitting one versioned package (tiles + style + glyphs + sprites + manifest), with the Risk-3 `package_version` contract established and machine-verified before either reader exists. The graph slot is reserved, not built (no reader to verify against), exactly as the foundations plan scoped it.

**2. Placeholder scan.** Every code step shows complete code; every run step has an exact command and expected output. Two facts are pinned from live checks this session: the planet build `20260708.pmtiles` (HTTP 200) and the bbox containment of the real walk track (1.3 to 2.0 km margins). One expected-output caveat: the exact text format of `pmtiles show` may differ by go-pmtiles version; the step asserts content (bounds/zoom/count), not exact text.

**3. Type consistency.** `region` (dict) and `region_path` (Path) flow through every `cmd_*` with one signature. The manifest keys written by `cmd_manifest` are exactly the keys `verify_package.py` reads (`schema`, `package_version`, `bbox`, `maxzoom`, `tiles`, `style`, `files[].path/bytes/sha256`). The style metadata key `apoc:package_version` is written by `gen_style.mjs` and read by the verifier. `MANIFEST_SCHEMA` and `pmtiles_bin` are defined once in `bake.py` and imported by the verifier.

---

## Execution Handoff

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks (superpowers:subagent-driven-development).
2. **Inline Execution** - execute the tasks in this session with checkpoints for review (superpowers:executing-plans).
