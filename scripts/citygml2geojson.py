#!/usr/bin/env python3
"""CityGML (PLATEAU bldg) -> newline-delimited GeoJSON for tippecanoe.

Conversion rules follow indigo-lab/plateau-lod2-mvt (README "ジオメトリ情報" / "属性情報"):

* If a bldg:Building has bldg:RoofSurface (LOD2), emit one GeoJSON Polygon per
  gml:Polygon under RoofSurface/bldg:lod2MultiSurface.  Height ``z`` is
  (max + min) / 2 of the roof polygon's exterior-ring z minus the ground level,
  where ground level is (max + min) / 2 of all GroundSurface exterior-ring z.
* Otherwise emit one Polygon per gml:Polygon under bldg:lod0RoofEdge (or
  bldg:lod0FootPrint) and take the height from bldg:lod1Solid (z max - z min);
  if that is missing, bldg:measuredHeight; if that is missing or <= 0, 0.
  (indigo-lab used measuredHeight only.  PLATEAU 2023+ data stores -9999 for
  unknown heights, so lod1Solid is preferred here.)

Parsing approach is modelled on PLATEAU-GIS-Converter (nusamai-citygml):
posList text is split into chunks of 3 (lat, lon, height) and the axis order is
swapped to (lon, lat) on output; only the highest LOD representation of a
surface is used (lod2MultiSurface, never lod3MultiSurface, to avoid duplicates).

Output properties (never null, single type per column for MLT):
  z_cm int    extrusion height in centimetres (metres * 100, rounded)
  lod  int    2 = RoofSurface, 1 = lod0 footprint + lod1Solid height,
              0 = lod0 footprint + measuredHeight (or 0)
  id   str    uro:buildingID (or gml:id), only with --with-id

Why an integer instead of indigo-lab's float ``z``: tippecanoe writes each numeric
value with the narrowest MVT type (sint for 12.0, float for 12.5, double for 5.4),
and the MVT -> MLT converter turns such a mixed-type column into a *string* column
("Double(5.4)", "Int(12)", ...), which breaks ``["get", "z"]`` in MapLibre.  An
integer column is always encoded as one type.  Use ``["*", ["get", "z_cm"], 0.01]``
for fill-extrusion-height.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Iterable

from lxml import etree

BLDG_NS = "http://www.opengis.net/citygml/building/2.0"
GML_NS = "http://www.opengis.net/gml"
B = "{%s}" % BLDG_NS
G = "{%s}" % GML_NS
# i-UR (uro) namespace changes with each version (…/uro/3.1, …/uro/3.2, …), so
# uro elements are matched by local name with the {*} wildcard.
URO_ANY = "{*}"

NULL_HEIGHT = -9999.0  # PLATEAU placeholder for "unknown"


# ----------------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------------


def _coords_of_ring(ring: etree._Element, dim_default: int) -> list[list[float]]:
    """Return [[lat, lon, z], ...] for a gml:LinearRing (posList or pos*)."""
    pl = ring.find(G + "posList")
    if pl is not None and pl.text:
        dim = int(pl.get("srsDimension") or dim_default)
        vals = [float(v) for v in pl.text.split()]
    else:
        pos = ring.findall(G + "pos")
        if not pos:
            return []
        dim = int(pos[0].get("srsDimension") or dim_default)
        vals = [float(v) for p in pos for v in (p.text or "").split()]
    if dim == 2:
        return [[vals[i], vals[i + 1], 0.0] for i in range(0, len(vals) - 1, 2)]
    return [vals[i : i + 3] for i in range(0, len(vals) - 2, 3)]


def _srs_dimension(el: etree._Element) -> int:
    for anc in el.iterancestors():
        d = anc.get("srsDimension")
        if d:
            return int(d)
    return 3


def _polygon_rings(poly: etree._Element) -> tuple[list[list[float]], list[list[list[float]]]]:
    dim = _srs_dimension(poly)
    ext = poly.find(G + "exterior")
    if ext is None:
        return [], []
    ext_ring = ext.find(".//" + G + "LinearRing")
    if ext_ring is None:
        return [], []
    exterior = _coords_of_ring(ext_ring, dim)
    interiors = []
    for inter in poly.findall(G + "interior"):
        r = inter.find(".//" + G + "LinearRing")
        if r is not None:
            c = _coords_of_ring(r, dim)
            if c:
                interiors.append(c)
    return exterior, interiors


def _ring_area_m2(ring: list[list[float]]) -> float:
    """Planar area (m^2) of a lat/lon ring using an equirectangular approximation."""
    if len(ring) < 3:
        return 0.0
    lat0 = sum(p[0] for p in ring) / len(ring)
    kx = 111_320.0 * math.cos(math.radians(lat0))
    ky = 110_540.0
    a = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][1] * kx, ring[i][0] * ky
        x2, y2 = ring[(i + 1) % n][1] * kx, ring[(i + 1) % n][0] * ky
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _to_geojson_ring(ring: list[list[float]], lonlat_input: bool, precision: int) -> list[list[float]]:
    out = []
    for p in ring:
        lon, lat = (p[0], p[1]) if lonlat_input else (p[1], p[0])
        out.append([round(lon, precision), round(lat, precision)])
    if out and out[0] != out[-1]:
        out.append(out[0])
    return out


def _zs(polys: Iterable[etree._Element]) -> list[float]:
    zs: list[float] = []
    for p in polys:
        ext, _ = _polygon_rings(p)
        zs.extend(c[2] for c in ext)
    return zs


def _mid(zs: list[float]) -> float:
    return (max(zs) + min(zs)) / 2.0


# ----------------------------------------------------------------------------
# per-building conversion
# ----------------------------------------------------------------------------


def _text_by_localname(el: etree._Element, name: str) -> str | None:
    e = el.find(".//" + URO_ANY + name)
    return e.text if e is not None else None


def _lod2_polys(surface_tag: str, bldg: etree._Element) -> list[etree._Element]:
    """gml:Polygon elements under <surface_tag>/bldg:lod2MultiSurface (BuildingParts included)."""
    out: list[etree._Element] = []
    for surf in bldg.iter(B + surface_tag):
        for ms in surf.findall(B + "lod2MultiSurface"):
            out.extend(ms.iter(G + "Polygon"))
    return out


def convert_building(bldg: etree._Element, opt: argparse.Namespace, stats: dict) -> list[dict]:
    stats["buildings"] += 1

    if opt.city:
        city = _text_by_localname(bldg, "city")
        if city not in opt.city:
            stats["skipped_other_city"] += 1
            return []
        stats["buildings_in_city"] += 1

    props_extra = {}
    if opt.with_id:
        bid = _text_by_localname(bldg, "buildingID") or bldg.get(G + "id") or ""
        props_extra["id"] = bid

    features: list[dict] = []

    roof_polys = _lod2_polys("RoofSurface", bldg)
    if opt.include_outer_floor:
        roof_polys += _lod2_polys("OuterFloorSurface", bldg)

    if roof_polys:
        stats["lod2_buildings"] += 1
        ground_zs = _zs(_lod2_polys("GroundSurface", bldg))
        if ground_zs:
            g = _mid(ground_zs)
        else:
            stats["lod2_without_ground"] += 1
            all_zs = _zs(p for ms in bldg.iter(B + "lod2MultiSurface") for p in ms.iter(G + "Polygon"))
            g = min(all_zs) if all_zs else 0.0

        for poly in roof_polys:
            ext, interiors = _polygon_rings(poly)
            if len(ext) < 3:
                stats["dropped_degenerate"] += 1
                continue
            if _ring_area_m2(ext) < opt.min_area:
                stats["dropped_small_area"] += 1
                continue
            z = max(0.0, _mid([c[2] for c in ext]) - g)
            rings = [_to_geojson_ring(ext, opt.lonlat, opt.precision)]
            rings += [_to_geojson_ring(r, opt.lonlat, opt.precision) for r in interiors if len(r) >= 3]
            features.append(_feature(rings, z, 2, props_extra))
            stats["features_lod2"] += 1
        return features

    if opt.lod2_only:
        stats["skipped_no_lod2"] += 1
        return []

    # ---- LOD0 footprint fallback -------------------------------------------
    src = bldg.find(B + "lod0RoofEdge")
    if src is None:
        src = bldg.find(B + "lod0FootPrint")
    polys: list[etree._Element] = list(src.iter(G + "Polygon")) if src is not None else []

    lod = 0
    height = 0.0
    solid = bldg.find(B + "lod1Solid")
    if solid is not None:
        zs = _zs(solid.iter(G + "Polygon"))
        if zs and max(zs) - min(zs) > 0:
            height = max(zs) - min(zs)
            lod = 1
        if not polys:
            # last resort: bottom face of the LOD1 solid
            bottom = None
            bottom_z = math.inf
            for p in solid.iter(G + "Polygon"):
                ext, _ = _polygon_rings(p)
                if ext:
                    mz = _mid([c[2] for c in ext])
                    if mz < bottom_z:
                        bottom_z, bottom = mz, p
            if bottom is not None:
                polys = [bottom]
                stats["fallback_lod1_bottom"] += 1
    if lod == 0:
        mh = bldg.findtext(B + "measuredHeight")
        try:
            mhv = float(mh) if mh is not None else None
        except ValueError:
            mhv = None
        if mhv is not None and mhv > 0:
            height = mhv
        else:
            stats["height_unknown"] += 1

    if not polys:
        stats["no_geometry"] += 1
        return []

    stats["lod0_buildings"] += 1
    for poly in polys:
        ext, interiors = _polygon_rings(poly)
        if len(ext) < 3:
            stats["dropped_degenerate"] += 1
            continue
        rings = [_to_geojson_ring(ext, opt.lonlat, opt.precision)]
        rings += [_to_geojson_ring(r, opt.lonlat, opt.precision) for r in interiors if len(r) >= 3]
        features.append(_feature(rings, height, lod, props_extra))
        stats["features_lod%d" % lod] += 1
    return features


def _feature(rings, z: float, lod: int, extra: dict) -> dict:
    props = {"z_cm": int(round(z * 100)), "lod": lod}
    props.update(extra)
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": rings}, "properties": props}


# ----------------------------------------------------------------------------
# per-file driver (runs in worker processes)
# ----------------------------------------------------------------------------

STAT_KEYS = [
    "buildings", "buildings_in_city", "skipped_other_city", "skipped_no_lod2",
    "lod2_buildings", "lod2_without_ground", "lod0_buildings", "fallback_lod1_bottom",
    "no_geometry", "height_unknown", "dropped_small_area", "dropped_degenerate",
    "features_lod2", "features_lod1", "features_lod0",
]


def convert_file(path: str, out_path: str, opt: argparse.Namespace) -> dict:
    stats = {k: 0 for k in STAT_KEYS}
    t0 = time.time()
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        ctx = etree.iterparse(path, events=("end",), tag=B + "Building", huge_tree=True)
        for _, el in ctx:
            for feat in convert_building(el, opt, stats):
                out.write(json.dumps(feat, separators=(",", ":"), ensure_ascii=False))
                out.write("\n")
            # free memory: clear the element and drop already-processed siblings
            el.clear()
            parent = el.getparent()
            while parent is not None and el.getprevious() is not None:
                del parent[0]
        del ctx
    stats["seconds"] = round(time.time() - t0, 1)
    stats["file"] = os.path.basename(path)
    return stats


def collect_inputs(paths: list[str]) -> list[str]:
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.gml")))
        elif any(ch in p for ch in "*?["):
            files += sorted(glob.glob(p))
        else:
            files.append(p)
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="CityGML .gml files, directories or globs")
    ap.add_argument("-o", "--output", required=True, help="output NDJSON path (.gz to gzip)")
    ap.add_argument("--min-area", type=float, default=0.1, help="drop roof polygons smaller than this (m^2), default 0.1")
    ap.add_argument("--city", action="append", help="keep only buildings whose uro:city equals this code (repeatable), e.g. 13101")
    ap.add_argument("--with-id", action="store_true", help="add 'id' property (uro:buildingID)")
    ap.add_argument("--include-outer-floor", action="store_true", help="treat bldg:OuterFloorSurface like RoofSurface")
    ap.add_argument("--lod2-only", action="store_true", help="skip buildings without LOD2 roof surfaces")
    ap.add_argument("--lonlat", action="store_true", help="input coordinates are already lon,lat (default: lat,lon as in EPSG:6697)")
    ap.add_argument("--precision", type=int, default=7, help="coordinate decimals, default 7")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="parallel worker processes")
    opt = ap.parse_args(argv)

    files = collect_inputs(opt.inputs)
    if not files:
        print("no input files", file=sys.stderr)
        return 2

    out_dir = os.path.dirname(os.path.abspath(opt.output)) or "."
    os.makedirs(out_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="c2g_", dir=out_dir)
    parts = [os.path.join(tmp_dir, "%05d.ndjson" % i) for i in range(len(files))]

    total = {k: 0 for k in STAT_KEYS}
    t0 = time.time()
    print(f"[citygml2geojson] {len(files)} files, {opt.workers} workers", file=sys.stderr)
    if opt.workers > 1 and len(files) > 1:
        with ProcessPoolExecutor(max_workers=opt.workers) as ex:
            futs = {ex.submit(convert_file, f, p, opt): f for f, p in zip(files, parts)}
            for fut in as_completed(futs):
                st = fut.result()
                _report(st, total)
    else:
        for f, p in zip(files, parts):
            _report(convert_file(f, p, opt), total)

    opener = gzip.open if opt.output.endswith(".gz") else open
    with opener(opt.output, "wb") as out:
        for p in parts:
            with open(p, "rb") as src:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            os.remove(p)
    os.rmdir(tmp_dir)

    total["features_total"] = total["features_lod2"] + total["features_lod1"] + total["features_lod0"]
    total["seconds"] = round(time.time() - t0, 1)
    total["output"] = opt.output
    print(json.dumps(total, indent=1), file=sys.stderr)
    return 0


def _report(st: dict, total: dict) -> None:
    for k in STAT_KEYS:
        total[k] += st[k]
    print(
        f"  {st['file']}: bldg={st['buildings']} lod2={st['lod2_buildings']} "
        f"feat={st['features_lod2'] + st['features_lod1'] + st['features_lod0']} "
        f"dropped_small={st['dropped_small_area']} {st['seconds']}s",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
