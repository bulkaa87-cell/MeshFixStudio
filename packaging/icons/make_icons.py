"""Draw the program icon: PNG (Linux), ICO (Windows) and ICNS (macOS).

The icons are made at build time, so the repository keeps no binary file:

    python packaging/icons/make_icons.py      (needs Pillow)

The picture: a triangle mesh (a wireframe) with a closed patch in green.
"""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BG = (34, 38, 43, 255)
LINE = (185, 196, 207, 255)
HOLE = (255, 45, 45, 255)
PATCH = (94, 240, 138, 255)


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 6
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)
    n = 4
    pad = size * 0.16
    step = (size - 2 * pad) / n
    pts = [[(pad + i * step + (step / 2 if j % 2 else 0), pad + j * step)
            for i in range(n + 1)] for j in range(n + 1)]
    tris = []
    for j in range(n):
        for i in range(n):
            a, b = pts[j][i], pts[j][i + 1]
            c, e = pts[j + 1][i], pts[j + 1][i + 1]
            tris += [(a, b, c), (b, e, c)]
    patch = {9, 10}
    w = max(2, size // 90)
    for k, tri in enumerate(tris):
        if k in patch:
            d.polygon(tri, fill=PATCH)
    for k, tri in enumerate(tris):
        d.line([*tri, tri[0]], fill=HOLE if k in patch else LINE, width=w,
               joint="curve")
    return img


def main() -> None:
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(
        os.path.join(HERE, "meshfix-studio.png"))
    img.save(os.path.join(HERE, "meshfix-studio.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                    (128, 128), (256, 256)])
    try:
        img.save(os.path.join(HERE, "meshfix-studio.icns"))
    except (OSError, ValueError, KeyError) as exc:
        print("no .icns:", exc)
    print("icons in", HERE)


if __name__ == "__main__":
    main()
