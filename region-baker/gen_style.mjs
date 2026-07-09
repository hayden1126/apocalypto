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
