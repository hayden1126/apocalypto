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
