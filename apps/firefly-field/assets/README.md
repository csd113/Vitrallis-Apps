# Firefly Field artwork

`meadow.png` is original artwork generated with OpenAI's built-in image generation
tool on 2026-09-14, then resized to the 480×272 logical canvas. No third-party
stock assets were imported. Its generation prompt was:

> Use case: stylized-concept. Asset type: production background texture for Firefly Field, a quiet ambient app on a 480x272 screen. Create an original polished pixel-art nighttime meadow background, landscape 16:9. Deep navy starry sky occupying upper 60%, a subtle small moon haze at upper right, layered distant blue-teal wooded hills at horizon around 60%, dark moss-green meadow below, delicate detailed fern and grass silhouettes framing bottom edge and outer corners. Spacious dark open center for animated golden firefly sprites to be composited by the app. Beautiful restrained palette, atmospheric depth, readable carefully placed pixel clusters and crisp silhouettes, calm natural mood. No fireflies or glowing dots in meadow (app animates them), no text, no UI, no border, no logos. Return the background artwork alone.

`firefly.png`, `grass.png` and `glow.png` preserve the package's original sprite
art as actual image assets rather than generating pixels on every launch.
`make_icon.py` remains the standard-library source for the existing package icon.

Each PNG has a `.rgba.z` runtime companion: zlib-compressed, tightly packed RGBA8
pixels, with dimensions fixed in the app. This keeps the runtime dependency-free.
The loader bounds decompression, requires exact pixel length and rejects trailing
or truncated streams before uploading. Textures upload once; animated draws stay
on the selected SDL renderer. The PNG files are editable source previews.

To regenerate companions after editing artwork, use an environment with Pillow:

```sh
python3 assets/pack_textures.py
```

Pillow is only an optional maintainer tool, not an app dependency. Startup fails
with an actionable asset filename if a packaged texture is missing or corrupt.
