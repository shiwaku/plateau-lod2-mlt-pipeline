#!/usr/bin/env bash
# Build MVT/MLT tiles from the NDJSON produced by citygml2geojson.py.
#
#   scripts/build_tiles.sh build/chiyoda-lod2.ndjson chiyoda-lod2 [--tessellate] [--dir] [--base-url URL]
#
# Outputs (in dist/):
#   <name>.mvt.pmtiles        MVT in PMTiles (tippecanoe, gzip tiles)
#   <name>.mlt.pmtiles        MLT in PMTiles (mlt convert, gzip tiles, tile_type = mlt)
# Optional, with --dir (for clients that cannot read PMTiles):
#   <name>/{z}/{x}/{y}.mlt    MLT directory for static hosting (uncompressed tiles)
#   <name>/tiles.json         TileJSON for the directory ("encoding": "mlt"); set --base-url
#
# Requires: tippecanoe >= 2.17 (PMTiles output), mlt CLI (cargo install mlt), python3 (--dir only).
# Run on Linux / macOS / WSL.  tippecanoe options follow indigo-lab/plateau-lod2-mvt
# (-ad -an -Z10 -z16 -l bldg -ai) with the output switched from a directory to PMTiles.

set -euo pipefail

INPUT=${1:?usage: build_tiles.sh INPUT.ndjson NAME [--tessellate] [--dir] [--base-url URL]}
NAME=${2:?usage: build_tiles.sh INPUT.ndjson NAME [--tessellate] [--dir] [--base-url URL]}
shift 2

TESSELLATE=()
MAKE_DIR=0
BASE_URL="https://example.com/${NAME}"
MINZOOM=${MINZOOM:-10}
MAXZOOM=${MAXZOOM:-16}
while [ $# -gt 0 ]; do
  case "$1" in
    --tessellate) TESSELLATE=(--tessellate) ;;
    --dir) MAKE_DIR=1 ;;
    --no-dir) MAKE_DIR=0 ;;
    --base-url) BASE_URL=$2; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

export PATH="$HOME/.cargo/bin:$PATH"
for tool in tippecanoe mlt; do
  command -v "$tool" >/dev/null || { echo "$tool not found" >&2; exit 1; }
done
[ "$MAKE_DIR" = 0 ] || command -v python3 >/dev/null || { echo "python3 not found (needed for --dir)" >&2; exit 1; }

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIST="$ROOT/dist"
BUILD="$ROOT/build"
mkdir -p "$DIST" "$BUILD"

# indigo-lab: -ad (--drop-densest-as-needed) -an (--drop-smallest-as-needed) -Z10 -z16 -l bldg -ai (--generate-ids)
# -T fixes attribute types so every feature has the same column type (MLT requirement).
TIPPE_OPTS=(
  -q --force
  -Z"$MINZOOM" -z"$MAXZOOM" -l bldg
  --drop-densest-as-needed --drop-smallest-as-needed
  --generate-ids
  --attribute-type=z_cm:int --attribute-type=lod:int
  -P
)

echo "== 1/2 tippecanoe -> $DIST/$NAME.mvt.pmtiles"
tippecanoe -o "$DIST/$NAME.mvt.pmtiles" "${TIPPE_OPTS[@]}" "$INPUT"

echo "== 2/2 mlt convert -> $DIST/$NAME.mlt.pmtiles"
mlt convert --tile-compression gzip "${TESSELLATE[@]}" "$DIST/$NAME.mvt.pmtiles" "$DIST/$NAME.mlt.pmtiles"

if [ "$MAKE_DIR" = 1 ]; then
  # Optional directory output.  mlt convert cannot write a directory from a PMTiles
  # input, so tippecanoe is run once more with directory output (uncompressed MVT).
  echo "== [--dir] tippecanoe -e -> $BUILD/${NAME}_mvt (uncompressed MVT directory)"
  rm -rf "$BUILD/${NAME}_mvt" "$DIST/$NAME"
  tippecanoe -e "$BUILD/${NAME}_mvt" --no-tile-compression "${TIPPE_OPTS[@]}" "$INPUT"

  echo "== [--dir] mlt convert -> $DIST/$NAME/{z}/{x}/{y}.mlt"
  mlt convert "${TESSELLATE[@]}" "$BUILD/${NAME}_mvt" "$DIST/$NAME"

  python3 - "$BUILD/${NAME}_mvt/metadata.json" "$DIST/$NAME/tiles.json" "$BASE_URL" "$NAME" <<'PY'
import json, sys
meta_path, out_path, base_url, name = sys.argv[1:5]
meta = json.load(open(meta_path, encoding="utf-8"))
inner = json.loads(meta.get("json", "{}"))
tilejson = {
    "tilejson": "3.0.0",
    "name": name,
    "description": "PLATEAU building roof surfaces (LOD2) / footprints with height attribute z_cm (centimetres)",
    "version": "1.0.0",
    "scheme": "xyz",
    "tiles": [base_url.rstrip("/") + "/{z}/{x}/{y}.mlt"],
    "format": "pbf",
    "encoding": "mlt",
    "minzoom": int(meta["minzoom"]),
    "maxzoom": int(meta["maxzoom"]),
    "bounds": [float(v) for v in meta["bounds"].split(",")],
    "center": [float(v) for v in meta["center"].split(",")],
    "vector_layers": inner.get("vector_layers", []),
    "attribution": "<a href='https://www.mlit.go.jp/plateau/'>国土交通省 Project PLATEAU</a> のデータを加工して作成",
}
json.dump(tilejson, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("wrote", out_path)
PY
fi

echo "== done"
ls -l "$DIST/$NAME".*.pmtiles
if [ "$MAKE_DIR" = 1 ]; then
  echo "$(find "$DIST/$NAME" -name '*.mlt' | wc -l) .mlt files, $(du -sh "$DIST/$NAME" | cut -f1) in $DIST/$NAME"
fi
