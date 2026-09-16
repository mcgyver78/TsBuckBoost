# Hardware for TsBuckBoost

Printable parts and wiring notes around the Victron Buck-Boost DC-DC converter. This is
a separate branch on purpose: the `latest` branch is installed onto GX devices through
kwindrem's SetupHelper, and these files have no business in that package.

The driver itself is on the [`latest`](../../tree/latest) branch.

## 80 mm fan mount, Buck-Boost 50 A

`fanmount_80mm_BuckBoost50A.step` — parametric source, open it in FreeCAD, Fusion or
anything else that reads STEP.

`fanmount_80mm_BuckBoost50A.stl` — ready to slice.

The converter reduces its output current as it heats up, well before the alarm
thresholds of the driver. A slow 80 mm fan is enough to keep the charge current at its
full value in a closed compartment.

Printed in PETG. PLA is a poor choice here — the mount sits on a device whose case gets
warm by design.

## Fan wiring

`fanwiring_dcssr_BuckBoost.svg` / `.pdf` — how to switch that fan from the converter
itself: pin 2 drives a DC solid state relay, the fan hangs on a fused tap off the
converter's IN or OUT stud, everything on one common ground.

The converter runs 12 V or 24 V on either side, so the drawing leaves both open: take
the supply from the side whose voltage matches the fan. Pin 1 is left alone — it is the
enable input, which the driver reads as /Mode.

Read the notes on the drawing before wiring. The important one: the SSR has to be DC
rated. An AC triac type conducts until the current crosses zero, which on DC never
happens, and the fan would never switch off.

## 92 mm fan mount, Buck-Boost 50 A

`cad/out/fanmount_92mm_BuckBoost50A.step` / `.stl` — the same mount drawn for a
Sunon GF92251B1-000U-AE9. Both sizes are kept on purpose: the 92 mm fan moves the same
air more slowly, and more quietly, wherever there is room for it.

## Cooling hood — a draft, not yet printed

`cad/out/concept_hood.step`, `print_hood.stl`, and `print_spacers_8mm/_10mm/_12mm.stl`.

The converter stands on four loose spacers at its own mounting points. There is
deliberately no base plate: the mounting surface itself is the floor of the lower duct.
The fan presses from above into a plenum over the fins, a duct along the left long side
takes part of that air underneath the device so both sides see flow, and both end faces
blow out. One M5 per corner runs through hood column, converter and spacer in a single
fastening.

Hood 151.9 × 61.0 × 216.0 mm. Print it standing on an end face, in GreenTEC Pro,
annealed — it sits over fins that reach 75 °C and the air inside it is hotter still, so
PLA is out. `print_hood.stl` is already oriented for that; do not rotate it.

Four things are open before this can be released: which side is "left" in the real
installation, whether cables block an end face, whether 61 mm of height fits, and which
spacer height to settle on. All three spacer heights are exported.

## cad/

The CadQuery scripts and the generated STEP/STL under `cad/out`.

The manufacturer's STEP model of the converter is deliberately **not** in here — it is
not ours to pass on. `duct_concept.py` uses it when the file sits next to the script and
falls back to a plain block when it does not. That block has no counterbores, so a
clearance check run without the real model reports the mount posts as colliding when
they do not. `cad/DESIGN-NOTES.md` names the file and says what is measured off it.

`cad/DESIGN-NOTES.md` carries the reasoning: every dimension was measured on that model
with CadQuery rather than taken from a datasheet, what was rejected along the way and
why, and the boolean and watertightness checks that should run before any release. Its
most important finding is that the two sides of the converter are not alike, which is
what decides how anything can be fastened to it.

Those notes are in German, unlike the rest of this repository.

## License

MIT, same as the driver.
