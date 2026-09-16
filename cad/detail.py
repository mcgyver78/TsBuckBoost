import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon

HOOD, HOODF = "#4a6b7c", "#cfdde4"
LOOSE, LOOSEF = "#b06a2c", "#f0dcc6"
CONV, CONVF = "#8a8a8a", "#e6e6e6"

fig, ax = plt.subplots(figsize=(10, 7.2))
ax.set_aspect("equal"); ax.axis("off")

def col(cx):
    """one column: d12 foot, 45 deg cone, d18 boss - drawn in section"""
    ax.add_patch(Rectangle((cx-6, 15.5), 12, 19.1, fc=HOODF, ec=HOOD, lw=1.6))
    ax.add_patch(Rectangle((cx-8, 34.6), 16, 14.6, fc=HOODF, ec=HOOD, lw=1.6))
    for s in (-1, 1):
        ax.plot([cx+s*2.9, cx+s*2.9], [14, 55], color="#c0392b", lw=1.1,
                ls=(0, (5, 3)))

# mounting surface
ax.add_patch(Rectangle((-40, -6), 190, 6, fc="#efeae2", ec="#b8ad9c", lw=1))
for x in range(-40, 150, 7):
    ax.plot([x, x-4], [0, -5], color="#b8ad9c", lw=0.7)

# loose spacers
for cx in (0, 60):
    ax.add_patch(Rectangle((cx-6.5, 0), 13, 10, fc=LOOSEF, ec=LOOSE, lw=1.6))

# converter with its fins
ax.add_patch(Rectangle((-25, 10), 110, 24.6, fc=CONVF, ec=CONV, lw=1.4))
for x in range(-24, 85, 5):
    if any(abs(x-c) < 9 for c in (0, 60)):
        continue
    ax.add_patch(Rectangle((x, 34.6), 2.4, 2.4, fc=CONVF, ec=CONV, lw=0.8))
for cx in (0, 60):
    ax.add_patch(Rectangle((cx-7.75, 14.5), 15.5, 20.1, fc="white", ec=CONV,
                           lw=1.0, ls=(0, (4, 2))))
ax.text(30, 22, "Buck-Boost", ha="center", va="center", color="#555", fontsize=10.5)
ax.text(30, 31, "Rippen 2,4 mm", ha="center", va="center", color="#999", fontsize=8.5)

# hood plate
ax.add_patch(Rectangle((-38, 49.2), 130, 4, fc=HOODF, ec=HOOD, lw=1.6))
for cx in (0, 60):
    col(cx)
    ax.add_patch(Rectangle((cx-7, 53.2), 14, 0.9, fc=HOODF, ec=HOOD, lw=1.6))

def lab(x, y, tx, ty, text, c, fs=10):
    ax.annotate("", xy=(x, y), xytext=(tx, ty),
                arrowprops=dict(arrowstyle="->", color=c, lw=1.1))
    ax.text(tx, ty, text, color=c, fontsize=fs, ha="left", va="center")

lab(66, 24, 96, 25, "d 12 Zapfen, 19,1 mm tief in der\nd 15,5 Senkung des Converters", HOOD)
lab(68, 36, 96, 41, "d 16 Schulter auf der gefraesten\nFlaeche - setzt die Plenumhoehe", HOOD)
lab(66.5, 5, 96, 8, "Distanzstueck, lose - traegt auf\nder gefraesten 25,9 mm Flaeche", LOOSE)
lab(62.9, 57, 96, 58, "M5 - eine durchgehende Verschraubung", "#c0392b")
ax.text(-38, 63, "Haube auf der Seite mit den Senkungen - die gefraesten Flaechen zeigen nach unten",
        color="#8a6a3a", fontsize=10.5)

ax.annotate("", xy=(-30, 34.6), xytext=(-30, 49.2),
            arrowprops=dict(arrowstyle="<->", color="#2b7a8c", lw=1.2))
ax.text(-32, 42, "14,6", color="#2b7a8c", fontsize=9, ha="right", va="center")
ax.plot([-33, 92], [34.6, 34.6], color="#2b7a8c", lw=0.6, ls=":")

ax.set_title("Kuehlhaube - Montagepunkt im Schnitt", loc="left",
             fontsize=15, weight="bold", color="#222", pad=16)
ax.set_xlim(-45, 300); ax.set_ylim(-12, 69)
fig.savefig("/root/work/fanmount/hood_detail.svg", bbox_inches="tight")
fig.savefig("/root/work/fanmount/hood_detail.png", dpi=150, bbox_inches="tight")
print("ok")
