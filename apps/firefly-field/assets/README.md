# Firefly Field artwork

The scene, radial glow, firefly sprite and grass sprites are generated once in
memory from original pixel-art routines in `main.py`, then uploaded as SDL
textures. They are deliberately not rendered into or uploaded from a CPU
framebuffer each frame. `make_icon.py` is a small standard-library generator
for the original package icon.
