# Hardware for TsBuckBoost

Printable and printable-on-paper parts around the Victron Buck-Boost DC-DC converter.
This is a separate branch on purpose: the `latest` branch is installed onto GX devices
through kwindrem's SetupHelper, and these files have no business in that package.

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

## License

MIT, same as the driver.
