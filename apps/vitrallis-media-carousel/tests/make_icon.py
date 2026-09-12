"""Reproduce the original code-native icon at the recommended launcher size."""
from pathlib import Path
from PIL import Image, ImageDraw


def main():
    scale = 4
    image = Image.new("RGBA", (512, 512))
    draw = ImageDraw.Draw(image)
    def box(bounds, radius, color):
        draw.rounded_rectangle(tuple(value * scale for value in bounds), radius * scale, fill=color)
    box((2, 2, 126, 126), 28, "#10191a")
    box((21, 20, 99, 90), 10, "#52746b")
    box((29, 29, 107, 99), 10, "#9aba8c")
    box((18, 38, 96, 108), 10, "#d4f48a")
    box((26, 46, 88, 94), 5, "#223b34")
    draw.ellipse((256, 208, 312, 264), fill="#d4f48a")
    draw.polygon([(x*scale, y*scale) for x, y in ((27, 87), (44, 65), (62, 85), (71, 74), (88, 91), (27, 91))], fill="#9aba8c")
    draw.polygon([(404, 212), (460, 252), (404, 292)], fill="#f1f3e8")
    image.resize((128, 128), Image.Resampling.LANCZOS).save(Path(__file__).resolve().parents[1] / "icon.png")


if __name__ == "__main__":
    main()
