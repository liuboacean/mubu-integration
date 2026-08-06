import os
from PIL import Image, ImageDraw, ImageFont

OUT = "/Users/liubo/WorkBuddy/2026-07-14-06-18-40/mubu-integration/assets"
os.makedirs(OUT, exist_ok=True)


def font(sz):
    for p in [
        "/System/Library/Fonts/Menlo.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        "/Library/Fonts/Menlo.ttf",
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


# ---------- social preview 1280x640 ----------
W, H = 1280, 640
im = Image.new("RGB", (W, H), (15, 23, 42))
dr = ImageDraw.Draw(im)
green = (34, 197, 94)
gray = (148, 163, 184)
white = (255, 255, 255)
dr.text((80, 110), "mubu-integration", font=font(70), fill=white)
dr.text((84, 212), "Markdown <-> Mubu    round-trip fidelity   ·   AI Agent Skill",
        font=font(30), fill=gray)
dr.rounded_rectangle([84, 300, 620, 372], radius=14, outline=green, width=3)
dr.text((112, 322), "-> true round-trip fidelity", font=font(30), fill=green)
# simple outline tree on the right
tx, ty = 830, 150
nodes = [
    (0, "product weekly"), (1, "last week"), (2, "ship release"),
    (2, "fix login bug"), (1, "this week"), (2, "perf tune"),
]
yy = ty
for lvl, txt in nodes:
    x = tx + lvl * 42
    dr.ellipse([x - 6, yy - 6, x + 6, yy + 6], fill=green if lvl == 0 else gray)
    dr.text((x + 16, yy - 11), txt, font=font(22), fill=white)
    yy += 46
im.save(os.path.join(OUT, "social-preview.png"))


# ---------- demo gif (terminal style) ----------
TW, TH = 900, 520
bg = (13, 17, 23)
fg = (210, 220, 230)
green = (63, 185, 80)
dim = (100, 116, 139)
steps = [
    ("$ cat weekly.md", fg),
    ("# product weekly", fg),
    ("- last week", fg),
    ("  - [x] ship release", fg),
    ("  - [ ] fix login bug", fg),
    ("- this week", fg),
    ("  - perf tune", fg),
    ("> note: sync to design", fg),
    ("", fg),
    ("$ mubu import weekly.md", green),
    ("  create Mubu doc -> doc_abc123", fg),
    ("", fg),
    ("$ mubu export doc_abc123 > out.md", green),
    ("  exported out.md", fg),
    ("", fg),
    ("$ diff weekly.md out.md", green),
    ("", fg),
    ("  (no output = byte-identical)", dim),
    (">> round-trip: zero diff", green),
]
f = font(20)
lh = 28
x0, y0 = 30, 30
frames = []
disp = []
for line, col in steps:
    disp.append((line, col))
    frame = Image.new("RGB", (TW, TH), bg)
    dd = ImageDraw.Draw(frame)
    yy = y0
    for ln, c in disp:
        dd.text((x0, yy), ln, font=f, fill=c)
        yy += lh
    dd.rectangle([x0 + 6, yy - 2, x0 + 15, yy + 14], fill=fg)  # cursor
    frames.append(frame)
    if line.startswith("$ mubu") or line.startswith(">>"):
        frames.append(frame)  # hold key moments
last = frames[-1]
for _ in range(8):
    frames.append(last)  # final hold

frames[0].save(
    os.path.join(OUT, "demo.gif"),
    save_all=True,
    append_images=frames[1:],
    duration=500,
    loop=0,
)
print("generated:", sorted(os.listdir(OUT)))
