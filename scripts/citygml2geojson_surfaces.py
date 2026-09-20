#!/usr/bin/env python3
"""Experimental CityGML (PLATEAU bldg / ubld, LOD2-LOD4) -> NDJSON for the LOD3 / LOD4 study.

The production converter (citygml2geojson.py) emits one Polygon per LOD2 roof
surface with a single height.  This script explores how much of an LOD3 / LOD4
model survives in a 2D vector tile with two height attributes:

  z_cm   top of the extrusion, centimetres above the reference level
  zb_cm  base of the extrusion, centimetres above the reference level
  kind   surface type (roof, floor, ceiling, wall, window, door, install, room, ...)
  lod    LOD of the geometry the polygon came from (2, 3 or 4)

Three modes, so the results can be compared:

  roof        RoofSurface polygons only, highest LOD available, base = 0.
              This is the production rule applied to lod3MultiSurface.
  horizontal  every upward-facing polygon (roofs, balcony tops, canopies,
              room ceilings, ...).  The base is the highest downward-facing
              polygon (balcony underside, room floor, ground) under it, so a
              balcony becomes a slab and a room becomes a box.
  all         every polygon, including walls and openings, as its 2D
              projection with zb/z = min/max z.  Vertical faces collapse to
              zero area and are dropped; the statistics say how many.

Orientation is taken from the polygon normal (Newell's method, exterior ring,
CityGML outward normals): nz > +0.3 faces up, nz < -0.3 faces down, else wall.

Reference level (--ref): ground = (max+min)/2 of GroundSurface z (production
rule); min = minimum z of the feature (for underground models, whose
elevations are absolute); or a number in metres.

Containers: by default the boundedBy surfaces and outerBuildingInstallation of
each Building (BuildingParts included).  --rooms switches to the Room solids
(interiorRoom/Room/lod4Solid) of each Building / UndergroundBuilding, which is
the natural unit for LOD4.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time
from collections import Counter

from lxml import etree
from shapely.geometry import Polygon as ShPolygon
from shapely.strtree import STRtree

BLDG_NS = "http://www.opengis.net/citygml/building/2.0"
GML_NS = "http://www.opengis.net/gml"
B = "{%s}" % BLDG_NS
G = "{%s}" % GML_NS

KIND_OF = {
    "RoofSurface": "roof", "WallSurface": "wall", "GroundSurface": "ground",
    "OuterCeilingSurface": "ceiling", "OuterFloorSurface": "floor",
    "CeilingSurface": "ceiling", "FloorSurface": "floor", "InteriorWallSurface": "wall",
    "ClosureSurface": "closure", "Window": "window", "Door": "door",
    "BuildingInstallation": "install", "IntBuildingInstallation": "install",
    "Room": "room",
}
UP, DOWN, WALL = "up", "down", "wall"


# ----------------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------------


def _ring_coords(ring, dim_default):
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
    return [vals[i:i + 3] for i in range(0, len(vals) - 2, 3)]


def _srs_dimension(el):
    for anc in el.iterancestors():
        d = anc.get("srsDimension")
        if d:
            return int(d)
    return 3


def _polygon_rings(poly):
    dim = _srs_dimension(poly)
    ext = poly.find(G + "exterior")
    if ext is None:
        return [], []
    r = ext.find(".//" + G + "LinearRing")
    if r is None:
        return [], []
    exterior = _ring_coords(r, dim)
    interiors = []
    for inter in poly.findall(G + "interior"):
        r = inter.find(".//" + G + "LinearRing")
        if r is not None:
            c = _ring_coords(r, dim)
            if len(c) >= 3:
                interiors.append(c)
    return exterior, interiors


class Local:
    """Equirectangular lat/lon -> metres around a reference latitude."""

    def __init__(self, lat0, lonlat):
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.ky = 110_540.0
        self.lonlat = lonlat

    def xy(self, p):
        lon, lat = (p[0], p[1]) if self.lonlat else (p[1], p[0])
        return lon * self.kx, lat * self.ky


def _normal(ring_m):
    """Unit normal of a 3D ring [(x, y, z), ...] by Newell's method."""
    nx = ny = nz = 0.0
    n = len(ring_m)
    for i in range(n):
        x1, y1, z1 = ring_m[i]
        x2, y2, z2 = ring_m[(i + 1) % n]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (nx / length, ny / length, nz / length) if length > 0 else (0.0, 0.0, 0.0)


def _to_lonlat_ring(ring, lonlat, precision):
    out = []
    for p in ring:
        lon, lat = (p[0], p[1]) if lonlat else (p[1], p[0])
        out.append([round(lon, precision), round(lat, precision)])
    if out and out[0] != out[-1]:
        out.append(out[0])
    return out


# ----------------------------------------------------------------------------
# CityGML walk
# ----------------------------------------------------------------------------


def _owner_of(poly):
    """Nearest thematic ancestor (RoofSurface, Window, Room, BuildingInstallation, ...)."""
    for anc in poly.iterancestors():
        t = etree.QName(anc).localname
        if t in KIND_OF:
            return anc, KIND_OF[t]
        if t in ("Building", "BuildingPart", "UndergroundBuilding"):
            return anc, "other"
    return None, "other"


def _highest_lod_geoms(owner):
    """Direct lodN(MultiSurface|Geometry|Solid) children of a thematic element, highest LOD only."""
    best, best_lod = [], -1
    for ch in owner:
        t = etree.QName(ch).localname
        if t.startswith("lod") and len(t) > 3 and t[3].isdigit():
            lod = int(t[3])
            if lod > best_lod:
                best, best_lod = [ch], lod
            elif lod == best_lod:
                best.append(ch)
    return best, best_lod


def collect_polygons(feature, rooms: bool):
    """Yield (polygon_element, kind, lod) for one Building / UndergroundBuilding.

    Default: boundedBy surfaces (+ their openings) and outer BuildingInstallations,
    each at its highest LOD.  --rooms: interior Room solids instead.
    """
    if rooms:
        for gi, room in enumerate(feature.iter(B + "Room")):
            geoms, lod = _highest_lod_geoms(room)
            for g in geoms:
                for p in g.iter(G + "Polygon"):
                    yield p, "room", lod, gi
        return

    room_index = {id(r): i + 1 for i, r in enumerate(feature.iter(B + "Room"))}

    def group_of(el):
        for anc in el.iterancestors():
            if id(anc) in room_index:
                return room_index[id(anc)]
        return 0

    owners = []
    for bb in feature.iter(B + "boundedBy"):
        for surf in bb:
            if etree.QName(surf).localname in KIND_OF:
                owners.append(surf)
                for op in surf.iter(B + "opening"):
                    for o in op:
                        if etree.QName(o).localname in ("Window", "Door"):
                            owners.append(o)
    for inst in feature.iter(B + "outerBuildingInstallation"):
        for o in inst:
            if etree.QName(o).localname == "BuildingInstallation":
                owners.append(o)
    seen = set()
    for owner in owners:
        geoms, lod = _highest_lod_geoms(owner)
        for g in geoms:
            for p in g.iter(G + "Polygon"):
                # a Window's polygons also sit inside the WallSurface subtree; emit once
                if id(p) in seen:
                    continue
                seen.add(id(p))
                # polygons under an opening belong to the opening, not the wall
                _, kind = _owner_of(p)
                yield p, kind, lod, group_of(owner)


def _has_lod(feature, lod):
    return (feature.find(".//" + B + "lod%dMultiSurface" % lod) is not None
            or feature.find(".//" + B + "lod%dSolid" % lod) is not None
            or feature.find(".//" + B + "lod%dGeometry" % lod) is not None)


# ----------------------------------------------------------------------------
# per-feature conversion
# ----------------------------------------------------------------------------


def convert_feature(feature, opt, stats):
    stats["features"] += 1
    if opt.city:
        c = feature.find(".//{*}city")
        if c is None or c.text not in opt.city:
            stats["skipped_other_city"] += 1
            return []
    if opt.require_lod and not _has_lod(feature, opt.require_lod):
        stats["skipped_no_required_lod"] += 1
        return []
    stats["features_converted"] += 1

    polys = list(collect_polygons(feature, opt.rooms))
    if not polys:
        stats["no_geometry"] += 1
        return []
    # PLATEAU stores the LOD2 and LOD3 shells as separate boundedBy elements, so
    # per surface kind keep only the highest LOD present, to avoid two overlapping
    # shells.  (Per kind, not per feature: the Takeshiba LOD4 model has its roof
    # only as lod2MultiSurface while walls and floors are lod4.)
    max_lod = {}
    for _, kind, lod, _ in polys:
        max_lod[kind] = max(max_lod.get(kind, -1), lod)
    kept = [p for p in polys if p[2] == max_lod[p[1]]]
    if len(kept) != len(polys):
        stats["dropped_lower_lod_polys"] += len(polys) - len(kept)
        polys = kept

    # local metric frame around the feature
    first_ext = None
    for p, _, _, _ in polys:
        ext, _ = _polygon_rings(p)
        if len(ext) >= 3:
            first_ext = ext
            break
    if first_ext is None:
        stats["no_geometry"] += 1
        return []
    lat0 = first_ext[0][1] if opt.lonlat else first_ext[0][0]
    loc = Local(lat0, opt.lonlat)

    faces = []
    all_z = []
    ground_z = []
    for p, kind, lod, group in polys:
        ext, ints = _polygon_rings(p)
        if len(ext) < 3:
            stats["dropped_degenerate"] += 1
            continue
        ring_m = [(*loc.xy(c), c[2]) for c in ext]
        zs = [c[2] for c in ext]
        all_z.extend(zs)
        if kind == "ground":
            ground_z.extend(zs)
        shp = ShPolygon([(x, y) for x, y, _ in ring_m],
                        [[loc.xy(c) for c in r] for r in ints] if ints else None)
        if not shp.is_valid:
            shp = shp.buffer(0)
        faces.append(dict(ext=ext, ints=ints, shp=shp, area=shp.area, nz=_normal(ring_m)[2],
                          zmin=min(zs), zmax=max(zs), zmid=(max(zs) + min(zs)) / 2,
                          kind=kind, lod=lod or 0, group=group))

    # reference level
    if opt.ref == "ground":
        if ground_z:
            ref = (max(ground_z) + min(ground_z)) / 2
        else:
            stats["no_ground_surface"] += 1
            ref = min(all_z)
    elif opt.ref == "min":
        ref = min(all_z)
    else:
        ref = float(opt.ref)

    def orient(f):
        if f["nz"] > 0.3:
            return UP
        if f["nz"] < -0.3:
            return DOWN
        return WALL

    out = []

    if opt.mode == "roof":
        for f in faces:
            if f["kind"] != "roof":
                continue
            if f["area"] < opt.min_area:
                stats["dropped_small_area"] += 1
                continue
            out.append(_feature(f, max(0.0, f["zmid"] - ref), 0.0, opt))
        return out

    if opt.mode == "all":
        for f in faces:
            stats["polys_" + f["kind"]] += 1
            if f["area"] < opt.min_area:
                stats["dropped_small_area"] += 1
                stats["collapsed_" + f["kind"]] += 1
                continue
            top = max(0.0, f["zmax"] - ref)
            base = min(top, max(0.0, f["zmin"] - ref))
            out.append(_feature(f, top, base, opt))
        return out

    # ---- horizontal: up-facing tops paired with the highest down-facing face below
    for f in faces:
        stats["faces_" + orient(f)] += 1
    stats["dropped_small_area"] += sum(1 for f in faces if orient(f) == UP and f["area"] < opt.min_area)
    # pair within a group: the whole shell for buildings, one Room for --rooms
    groups = sorted({f["group"] for f in faces})
    for gid in groups:
        gfaces = [f for f in faces if f["group"] == gid]
        tops = [f for f in gfaces if orient(f) == UP and f["area"] >= opt.min_area]
        bottoms = [f for f in gfaces if orient(f) == DOWN and f["area"] >= opt.min_area]
        fallback = min(f["zmin"] for f in gfaces) if gid != 0 else ref
        tree = STRtree([b["shp"] for b in bottoms]) if bottoms else None
        for t in tops:
            base_z = None
            if tree is not None:
                for i in tree.query(t["shp"]):
                    b = bottoms[i]
                    if b["zmid"] >= t["zmid"] - 0.05:
                        continue
                    inter = t["shp"].intersection(b["shp"]).area
                    if inter >= opt.overlap * t["area"] and (base_z is None or b["zmid"] > base_z):
                        base_z = b["zmid"]
            if base_z is None:
                stats["tops_without_base"] += 1
                base_z = fallback
            else:
                stats["tops_with_base"] += 1
            top = max(0.0, t["zmid"] - ref)
            base = min(top, max(0.0, base_z - ref))
            if top - base < opt.min_thickness:
                stats["dropped_thin"] += 1
                continue
            out.append(_feature(t, top, base, opt))
    return out


def _feature(f, top_m, base_m, opt):
    rings = [_to_lonlat_ring(f["ext"], opt.lonlat, opt.precision)]
    rings += [_to_lonlat_ring(r, opt.lonlat, opt.precision) for r in f["ints"]]
    props = {"z_cm": int(round(top_m * 100)), "zb_cm": int(round(base_m * 100)),
             "kind": f["kind"], "lod": int(f["lod"])}
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": rings}, "properties": props}


# ----------------------------------------------------------------------------
# driver
# ----------------------------------------------------------------------------


def _is_top_feature(el):
    name = etree.QName(el).localname
    if name not in ("Building", "UndergroundBuilding"):
        return False
    # BuildingParts etc. nested inside a Building are handled with their parent
    return not any(etree.QName(a).localname in ("Building", "UndergroundBuilding") for a in el.iterancestors())


def convert_file(path, out, opt, stats):
    t0 = time.time()
    n = 0
    ctx = etree.iterparse(path, events=("end",), huge_tree=True)
    for _, el in ctx:
        if not isinstance(el.tag, str) or not _is_top_feature(el):
            continue
        for feat in convert_feature(el, opt, stats):
            out.write(json.dumps(feat, separators=(",", ":"), ensure_ascii=False))
            out.write("\n")
            n += 1
        el.clear()
        parent = el.getparent()
        while parent is not None and el.getprevious() is not None:
            del parent[0]
    print(f"  {os.path.basename(path)}: features={n} {time.time() - t0:.1f}s", file=sys.stderr)
    return n


def collect_inputs(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.gml")))
        elif any(ch in p for ch in "*?["):
            files += sorted(glob.glob(p))
        else:
            files.append(p)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--mode", choices=["roof", "horizontal", "all"], default="horizontal")
    ap.add_argument("--rooms", action="store_true", help="use interiorRoom/Room solids instead of the outer shell")
    ap.add_argument("--ref", default="ground", help="ground | min | <metres> (default ground)")
    ap.add_argument("--require-lod", type=int, default=0, help="skip features without lodN geometry, e.g. 3")
    ap.add_argument("--city", action="append", help="keep only uro:city == CODE (repeatable)")
    ap.add_argument("--min-area", type=float, default=0.1, help="drop polygons under this 2D area in m^2")
    ap.add_argument("--min-thickness", type=float, default=0.0, help="horizontal: drop slabs thinner than this (m)")
    ap.add_argument("--overlap", type=float, default=0.5, help="horizontal: base must cover this fraction of the top")
    ap.add_argument("--lonlat", action="store_true", help="input is lon,lat (default lat,lon as in EPSG:6697)")
    ap.add_argument("--precision", type=int, default=7)
    opt = ap.parse_args(argv)

    files = collect_inputs(opt.inputs)
    if not files:
        print("no input files", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(opt.output)) or ".", exist_ok=True)
    stats = Counter()
    t0 = time.time()
    total = 0
    with open(opt.output, "w", encoding="utf-8", newline="\n") as out:
        for f in files:
            total += convert_file(f, out, opt, stats)
    stats["features_out"] = total
    stats["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(dict(sorted(stats.items())), indent=1, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
