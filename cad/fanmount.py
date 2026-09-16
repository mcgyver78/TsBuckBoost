"""
Parametric fan mount for the Victron Buck-Boost 50 A (top systems TS800C5).

Rebuilt from fanmount_80mm_BuckBoost50A.step, measured with CadQuery. The
converter-side interface - post positions, standoff height, screw holes and
counterbores - is reproduced exactly; only the fan side is parametric.

Coordinate system is the one of the original STEP file (and of the converter
model): the converter surface is Y = 0, the mount stands in -Y, the long axis
of the converter is Z. Internally the model is built with Z up and rotated at
the end, which keeps the sketch code readable.

    python3 fanmount.py 80      -> fanmount_80mm_BuckBoost50A.{step,stl}
    python3 fanmount.py 92      -> fanmount_92mm_BuckBoost50A.{step,stl}
"""
import math
import sys

import cadquery as cq

# ---------------------------------------------------------------- fan sizes
# frame size: (screw spacing, bore diameter, plate size)
# Screw spacing and bore are the industry standard for axial fans of that
# frame size; 92 mm verified against the Sunon GF92251B1-000U-AE9 datasheet.
FANS = {
    80:  dict(spacing=71.5, bore=76.0, plate=96.0),
    92:  dict(spacing=82.5, bore=88.0, plate=108.0),
    120: dict(spacing=105.0, bore=115.0, plate=130.0),   # untested, envelope grows
}
FAN_SCREW_D = 4.5          # clearance for M4, as in the original

# ------------------------------------------------- converter-side interface
# All of these are measured from the original and must not change.
FAN_CX, FAN_CY = -36.95, -3.41      # fan axis, in converter coordinates
POSTS = [(-89.95, -103.41), (-89.95, 96.59), (16.05, -103.41), (16.05, 96.59)]
STANDOFF = 50.0            # underside of the plate above the converter
PLATE_T = 4.0              # plate thickness
POST_D_LOWER = 12.0        # slim section sitting on the converter
POST_D_UPPER = 18.0        # boss carrying the plate
POST_STEP = 20.1           # where the slim section becomes the boss
SCREW_D = 5.6              # clearance for M5 into the converter
SCREW_HEAD_D = 10.2        # access shaft for the screw head / socket
SCREW_HEAD_Z = 21.6        # the head seats here
ARM_FOOT = 18.0            # width of the arm where it leaves the plate
FILLET = 3.0               # rounding of all upright edges of the plate


def hull_2d(points):
    """Convex hull, Andrew's monotone chain."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def circle_points(cx, cy, r, n=48):
    return [(cx + r * math.cos(2 * math.pi * i / n),
             cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def build(fan_size):
    fan = FANS[fan_size]
    half = fan["plate"] / 2.0

    # --- plate outline: square over the fan, plus a tapered arm to each post
    plate = (cq.Workplane("XY")
             .center(FAN_CX, FAN_CY).rect(fan["plate"], fan["plate"])
             .extrude(PLATE_T))

    for px, py in POSTS:
        sx = 1 if px > FAN_CX else -1
        sy = 1 if py > FAN_CY else -1
        # the arm leaves the plate over ARM_FOOT next to the nearest corner
        foot = [(FAN_CX + sx * half, FAN_CY + sy * half),
                (FAN_CX + sx * (half - ARM_FOOT), FAN_CY + sy * half),
                (FAN_CX + sx * half, FAN_CY + sy * (half - ARM_FOOT))]
        pts = hull_2d(foot + circle_points(px, py, POST_D_UPPER / 2.0))
        arm = (cq.Workplane("XY").polyline(pts).close().extrude(PLATE_T))
        plate = plate.union(arm)

    plate = plate.edges("|Z").fillet(FILLET)
    plate = plate.translate((0, 0, STANDOFF))

    # --- posts
    result = plate
    for px, py in POSTS:
        post = (cq.Workplane("XY").center(px, py)
                .circle(POST_D_LOWER / 2.0).extrude(POST_STEP)
                .faces(">Z").workplane()
                .circle(POST_D_UPPER / 2.0).extrude(STANDOFF - POST_STEP))
        result = result.union(post)

    # --- holes: screw through the post, access shaft up through the plate
    for px, py in POSTS:
        result = result.cut(cq.Workplane("XY").center(px, py)
                            .circle(SCREW_D / 2.0).extrude(SCREW_HEAD_Z))
        result = result.cut(cq.Workplane("XY").center(px, py)
                            .workplane(offset=SCREW_HEAD_Z)
                            .circle(SCREW_HEAD_D / 2.0)
                            .extrude(STANDOFF + PLATE_T - SCREW_HEAD_Z))

    # --- fan bore and its four screw holes
    z0, z1 = STANDOFF, STANDOFF + PLATE_T
    result = result.cut(cq.Workplane("XY").center(FAN_CX, FAN_CY)
                        .workplane(offset=z0).circle(fan["bore"] / 2.0)
                        .extrude(PLATE_T))
    s = fan["spacing"] / 2.0
    for dx in (-s, s):
        for dy in (-s, s):
            result = result.cut(cq.Workplane("XY")
                                .center(FAN_CX + dx, FAN_CY + dy)
                                .workplane(offset=z0)
                                .circle(FAN_SCREW_D / 2.0).extrude(PLATE_T))

    # into converter coordinates: local +Z (away from the converter) -> global -Y
    return result.rotate((0, 0, 0), (1, 0, 0), 90)


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 92
    model = build(size)
    name = "fanmount_%dmm_BuckBoost50A" % size
    cq.exporters.export(model, name + ".step")
    cq.exporters.export(model, name + ".stl",
                        tolerance=0.01, angularTolerance=0.1)
    bb = model.val().BoundingBox()
    print("%s  %.1f x %.1f x %.1f mm  %.1f cm3"
          % (name, bb.xlen, bb.ylen, bb.zlen, model.val().Volume() / 1000.0))


if __name__ == "__main__":
    main()
