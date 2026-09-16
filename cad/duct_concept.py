"""
Concept study: cooling hood for the Victron Buck-Boost 50 A, flow optimised.

The converter stands 10 mm off its mounting surface on four spacers at its own
mounting points; the mounting surface is the floor of the lower channel. The fan
presses air into a plenum over the fins, a duct on the left long side takes part
of it down into that lower channel, and the air leaves at the two short ends.

Flow work compared with the first, rectangular draft:
  * the cross section is now one swept profile with radii instead of boxes
  * R12 where the plenum turns down into the duct  (outside of that bend)
  * R18 ramp where the duct turns under the converter (outside of that bend)
  * R8 at the far wall so the plenum does not run into a square dead end
  * the fan bore opens conically downwards, so the jet is not cut by a sharp lip
A sharp mitre bend costs roughly K = 1.1..1.3 dynamic heads, a bend with
r/d around 0.7 about K = 0.3 - that is where the gain comes from.

Parts:
  hood    - swept profile with top plate, fan opening, both walls and the four
            columns that bridge the plenum down to the converter. Those columns
            are part of the hood, printed with it - only that way is the hood
            held at its corners and the plenum height defined. They are the
            only thing in the hood that touches the converter: each one plugs
            d12 into the converter's own d15.5 recess and seats with a d16
            shoulder on the machined land around it, as the 80/92 mm fan mount
            does it. That locates the hood positively and sets the plenum
            height on a machined face; the M5 then makes one continuous bolted
            joint and no load is ever carried by the heat sink.
  spacer  - 4x, loose, at the converter's mounting points, in 8 / 10 / 12 mm
One M5 per corner goes from the top through hood column, converter and loose
spacer into the mounting surface and clamps the whole stack.

Printing (CR-10 V2, 0.4 nozzle). The hood stands on one short end, 214 mm
tall - the swept profile already runs along Z, so the exported STL needs no
rotating. In that orientation the body is a constant cross section: every wall
is vertical, nothing needs support, and the layer lines run across the air path
rather than along it, so a delaminating layer cannot open a leak down the duct.
What the geometry does for the printer:
  * walls 3.2 mm = 8 lines of 0.4, so with 4 wall lines they come out solid
  * a flat pad around each screw hole - the outer surface is steeply sloped
    there (22 degrees), so a screw head would otherwise bear on one edge
  * horizontal holes 0.2 mm larger, since they print with a slightly sagging
    crown: M5 5.8, fan screws 4.7
  * the columns are the only real overhang - each starts as a small sliver
    hanging off the plate, inside the plenum where nothing touches. Add a
    support blocker around the rest of the model if you want them crisp.
Material: GreenTEC Pro, annealed - the hood sits over fins that reach 75 C and
the air inside it is hotter still. PLA is not an option here.
The spacers print standing on their axis; print_spacers_*.stl has the four of
them grouped together.

Which way up: the hood goes on the RECESSED side of the converter, the same
side the fan mount bolts to. The other side carries the two 25.9 mm milled
lands and faces the mounting surface, where the loose spacers bear on them.
Both sides are finned alike - 2.4 mm ribs at 10 mm pitch - so nothing is lost.

Converter coordinates of the manufacturer's STEP model are kept, with the part
turned over about its long axis so the recessed side is up:
  body   X -96.5 .. 22.5   Y 0 .. 37   Z -110.0 .. 103.0
  holes at X -89.95 / 16.05, Z -103.41 / 96.59
  at each hole: fin tips Y 37, machined land Y 34.6, clear d15.5 recess down
  to Y 14.5, then d10.8 and the d5.52 through hole
"""
import math

import cadquery as cq

# ---------------------------------------------------------------- converter
CX0, CX1 = -96.5, 22.5
CY0, CY1 = 0.0, 37.0
CZ0, CZ1 = -109.9, 103.2
HOLES = [(-89.95, -103.41), (-89.95, 96.59), (16.05, -103.41), (16.05, 96.59)]

# ------------------------------------------------------------- concept sizes
SIDE = -1          # -1 = duct on the -X side. +1 mirrors the whole hood.
GAP_BOTTOM = 10.0  # air channel under the converter = spacer height
GAP_TOP = 8.0      # plenum over the fins, in the middle
DUCT_W = 26.0      # clear width of the side duct
WALL = 3.2         # 8 lines of 0.4 - the walls come out as pure perimeter
PLATE_T = 4.0      # thickness of the plate at the exits, 10 lines
FIT = 0.5
WALL_LIFT = 2.0    # the walls stop short of the surface, a foam strip seals
EXIT_RISE = 4.0    # the plenum opens by this much towards the exits
EXIT_LEN = 30.0    # over this length

R_TOP = 12.0       # plenum -> duct
R_BOT = 18.0       # duct -> lower channel
R_FAR = 8.0        # far wall into the plenum ceiling

FAN_BORE = 88.0
FAN_FLARE = 6.0    # the bore opens by this much towards the plenum
FAN_SPACING = 82.5
FAN_SCREW = 4.7    # M4 clearance, 0.2 added: printed lying down
FAN_OFFSET = 0.0   # move the fan towards the duct if the lower path needs more
# mounting points, measured on the manufacturer's STEP. Each hole sits at the
# bottom of a clear d15.5 recess, 22.5 mm below the fin tips, with a flat
# machined land 2.4 mm below the tips around its mouth. The fan mount plugs
# into it with POST_D_LOWER=12 over POST_STEP=20.1 - the same numbers here.
PLUG_D = 12.0      # goes down into the recess
BOSS_D = 16.0      # sits on the land and carries the plate. 18 as in the
                   # fan mount does not fit: a cast feature next to one hole
                   # leaves the land clear only out to d16.5
RECESS_DEPTH = 22.5
LAND_DROP = 2.4
PLUG_CLEAR = 1.0   # the plug stops short of the recess floor, so the
                   # shoulder on the land is the only datum
PLUG_LEN = RECESS_DEPTH - LAND_DROP - PLUG_CLEAR
POST_D = BOSS_D
PAD_D = 14.0       # flat seat for the screw head on the sloped outer surface
SPACER_D = 13.0
SCREW_D = 5.6      # M5 clearance in the spacers, printed standing up
SCREW_D_H = 5.8    # same hole in the hood, where it prints lying down

# derived levels
Y_FLOOR = CY0 - GAP_BOTTOM
Y_PLEN1 = CY1 + GAP_TOP                  # ceiling in the middle
Y_TOP1 = Y_PLEN1 + PLATE_T               # outer height in the middle
Y_WALL = Y_FLOOR + WALL_LIFT             # lower edge of both walls
XW_IN = CX0 - DUCT_W          # inner face of the duct wall
XW_OUT = XW_IN - WALL
XR_IN = CX1 + FIT             # inner face of the far wall
XR_OUT = XR_IN + WALL
FAN_CX = (CX0 + CX1) / 2.0 + FAN_OFFSET
FAN_CZ = (CZ0 + CZ1) / 2.0
# the hood covers the whole converter plus the bosses at the outer holes
_R = max(POST_D, PAD_D) / 2.0
ZL = min(CZ0 - 0.5, min(hz for _, hz in HOLES) - _R)
ZR = max(CZ1 + 0.5, max(hz for _, hz in HOLES) + _R)


def arc_mid(cx, cy, r, a0, a1):
    a = (a0 + a1) / 2.0
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def profile():
    """Closed cross section of the hood in the X-Y plane."""
    c_far = (XR_IN - R_FAR, Y_PLEN1 - R_FAR)
    c_top = (XW_IN + R_TOP, Y_PLEN1 - R_TOP)
    c_bot = (XW_IN + R_BOT, Y_WALL + R_BOT)
    w = (cq.Workplane("XY")
         .moveTo(XW_OUT, Y_WALL)
         .lineTo(XW_OUT, Y_TOP1)
         .lineTo(XR_OUT, Y_TOP1)
         .lineTo(XR_OUT, Y_WALL)
         .lineTo(XR_IN, Y_WALL)
         .lineTo(XR_IN, Y_PLEN1 - R_FAR)
         .threePointArc(arc_mid(c_far[0], c_far[1], R_FAR, 0.0, math.pi / 2),
                        (XR_IN - R_FAR, Y_PLEN1))
         .lineTo(XW_IN + R_TOP, Y_PLEN1)
         .threePointArc(arc_mid(c_top[0], c_top[1], R_TOP, math.pi / 2, math.pi),
                        (XW_IN, Y_PLEN1 - R_TOP))
         .lineTo(XW_IN, Y_WALL + R_BOT)
         .threePointArc(arc_mid(c_bot[0], c_bot[1], R_BOT, math.pi, 1.5 * math.pi),
                        (XW_IN + R_BOT, Y_WALL))
         .close())
    return w


def post(x, z, y0, y1, d):
    return cq.Workplane("XY").newObject(
        [cq.Solid.makeCylinder(d / 2.0, y1 - y0, cq.Vector(x, y0, z),
                               cq.Vector(0, 1, 0))])


def prism_zy(pts_zy, x0, x1):
    """Prism from a polygon given in the Z-Y plane, extruded along X."""
    pts = [cq.Vector(x0, y, z) for z, y in pts_zy]
    face = cq.Face.makeFromWires(cq.Wire.makePolygon(pts + [pts[0]]))
    return cq.Workplane("XY").newObject(
        [cq.Solid.extrudeLinear(face, cq.Vector(x1 - x0, 0, 0))])


def column(hx, hz, top):
    """One mounting column, built like the posts of the 80/92 mm fan mount.

    A d12 plug reaches 20.1 mm down into the converter's own recess and a d18
    boss above it seats on the machined land around the recess mouth. That is
    the form fit: the hood is located by the recesses, not by friction, and the
    distance between the converter surface and the hood is set by the shoulder
    on a machined face, not by how hard the screws are pulled up.

    It also means the hood belongs on the recessed side of the converter - the
    same side the fan mount bolts to. The other side carries the two 25.9 mm
    milled lands, and the loose spacers bear on those.
    """
    r = post(hx, hz, CY1 - RECESS_DEPTH + PLUG_CLEAR, CY1 - LAND_DROP, PLUG_D)
    return r.union(post(hx, hz, CY1 - LAND_DROP, top, BOSS_D))


def wedge(y0, y1, z_flat, z_end, x0, x1):
    """Triangular prism used to open the plenum towards an exit."""
    pts = [cq.Vector(x0, y0, z_flat), cq.Vector(x0, y0, z_end),
           cq.Vector(x0, y1, z_end)]
    face = cq.Face.makeFromWires(cq.Wire.makePolygon(pts + [pts[0]]))
    return cq.Workplane("XY").newObject(
        [cq.Solid.extrudeLinear(face, cq.Vector(x1 - x0, 0, 0))])


def ceiling(z):
    """Height of the plenum ceiling at z - it rises towards the two exits."""
    y = Y_PLEN1
    for z_flat, z_end in ((CZ1 - EXIT_LEN, ZR), (CZ0 + EXIT_LEN, ZL)):
        f = (z - z_flat) / (z_end - z_flat)
        if f > 0.0:
            y = max(y, Y_PLEN1 + EXIT_RISE * min(f, 1.0))
    return y


def hood():
    r = profile().extrude(ZR - ZL).translate((0, 0, ZL))
    # exits: ceiling and outer surface both rise over the last EXIT_LEN,
    # so the plate stays 4 mm thin and the channel opens up
    for z_flat, z_end in ((CZ1 - EXIT_LEN, ZR), (CZ0 + EXIT_LEN, ZL)):
        # 0.02 past the far wall: a cut face exactly coplanar with the wall
        # leaves a sliver void in the solid
        r = r.cut(wedge(Y_PLEN1, Y_PLEN1 + EXIT_RISE, z_flat, z_end,
                        XW_IN, XR_IN + 0.02))
        r = r.union(wedge(Y_TOP1, Y_TOP1 + EXIT_RISE, z_flat, z_end,
                          XW_OUT, XR_OUT))
    # The four columns bridging the plenum are part of the hood. All four stand
    # inside the ramped zone, where the ceiling is up to 3 mm higher than in the
    # middle, so each one is grown to the ceiling above its own footprint - a
    # column ending at the flat height would float in the plenum.
    for hx, hz in HOLES:
        top = max(ceiling(hz - POST_D / 2.0),
                  ceiling(hz + POST_D / 2.0)) + 0.5
        r = r.union(column(hx, hz, top))
        # flat seat for the screw head - the outer surface is sloped here
        r = r.union(post(hx, hz, Y_TOP1, Y_TOP1 + EXIT_RISE, PAD_D))
    for hx, hz in HOLES:
        r = r.cut(post(hx, hz, CY1 - RECESS_DEPTH - 1.0,
                       Y_TOP1 + EXIT_RISE + 1.0, SCREW_D_H))
    # fan opening, opening up conically towards the plenum
    cone = cq.Workplane("XY").newObject([cq.Solid.makeCone(
        FAN_BORE / 2.0, FAN_BORE / 2.0 + FAN_FLARE, PLATE_T + 0.2,
        cq.Vector(FAN_CX, Y_TOP1 + 0.1, FAN_CZ), cq.Vector(0, -1, 0))])
    r = r.cut(cone)
    s = FAN_SPACING / 2.0
    for dx in (-s, s):
        for dz in (-s, s):
            r = r.cut(post(FAN_CX + dx, FAN_CZ + dz, Y_PLEN1, Y_TOP1, FAN_SCREW))
    if SIDE > 0:
        r = r.mirror("YZ", (FAN_CX, 0, 0))
    return r


def spacers(height=None):
    h = GAP_BOTTOM if height is None else height
    r = None
    for hx, hz in HOLES:
        p = post(hx, hz, -h, CY0, SPACER_D).cut(post(hx, hz, -h, CY0, SCREW_D))
        r = p if r is None else r.union(p)
    return r


def spacers_print(height):
    """The four spacers standing on their axis, close together on the bed."""
    p = 22.0
    r = None
    for dx in (-p / 2.0, p / 2.0):
        for dz in (-p / 2.0, p / 2.0):
            c = (cq.Workplane("XY").center(dx, dz).circle(SPACER_D / 2.0)
                 .extrude(height)
                 .cut(cq.Workplane("XY").center(dx, dz)
                      .circle(SCREW_D / 2.0).extrude(height)))
            r = c if r is None else r.union(c)
    return r


def hood_print():
    """The hood as it goes on the bed: standing on the -Z end, z0 = 0.

    Nothing is rotated - the swept profile already runs along Z, which is the
    build direction. Printed this way the whole body is a constant cross
    section: vertical walls, no support anywhere, and the layers run across
    the air path instead of along it.
    """
    return hood().translate((0, 0, -ZL))


CONVERTER_STEP = "871efab6-50ABuckBoostDCDCconverterstep.STEP"


def converter(path=CONVERTER_STEP):
    """The manufacturer's model, turned so the recessed side faces the hood.

    Falls back to a plain block when the STEP is not next to this script - the
    block has no recesses, so a clearance check against it will report the
    plugs as a collision.
    """
    import os
    if os.path.exists(path):
        # turned over about its long axis - a mirror would be the other hand.
        # The hole pattern is not centred, so the flip is followed by a shift
        # that puts the four holes back on HOLES.
        dz = 2.0 * sum(hz for _, hz in HOLES) / len(HOLES)
        c = cq.importers.importStep(path)
        return c.rotate((0, 0, 0), (1, 0, 0), 180).translate((0, CY1, dz))
    return cq.Workplane("XY").newObject(
        [cq.Solid.makeBox(CX1 - CX0, CY1 - CY0, CZ1 - CZ0,
                          cq.Vector(CX0, CY0, CZ0))])


def save(shape, name, step=True):
    if step:
        cq.exporters.export(shape, name + ".step")
    cq.exporters.export(shape, name + ".stl", tolerance=0.02,
                        angularTolerance=0.2)


if __name__ == "__main__":
    h = hood()
    save(h, "concept_hood")
    save(hood_print(), "print_hood", step=False)
    parts = [("hood", h)]
    for mm in (8, 10, 12):
        sp = spacers(mm)
        save(sp, "concept_spacers_%dmm" % mm)
        save(spacers_print(mm), "print_spacers_%dmm" % mm, step=False)
        parts.append(("spacer %d" % mm, sp))
    for n, s in parts:
        b = s.val().BoundingBox()
        print("%-8s %6.1f x %6.1f x %6.1f mm   %6.1f cm3"
              % (n, b.xlen, b.ylen, b.zlen, s.val().Volume() / 1000.0))
