"""Render the existing c·b wordmark into app icons (development-only Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = Path('/System/Library/Fonts/Supplemental/Georgia Italic.ttf')
size = 1024
font = ImageFont.truetype(str(FONT), 400)
image = Image.new('RGB', (size, size), '#2f4d3d')
draw = ImageDraw.Draw(image)
word = 'c·b'
box = draw.textbbox((0, 0), word, font=font)
x = (size - draw.textlength(word, font=font)) / 2
y = (size - (box[3] - box[1])) / 2 - box[1]
for index, letter in enumerate(word):
    draw.text((x + draw.textlength(word[:index], font=font), y), letter,
              font=font, fill='#dce8b7' if letter == '·' else '#f7f4ee')

directory = ROOT / 'web' / 'icons'
directory.mkdir(exist_ok=True)
for side in (180, 192, 512):
    image.resize((side, side), Image.Resampling.LANCZOS).save(directory / f'icon-{side}.png', optimize=True)
