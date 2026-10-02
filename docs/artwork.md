# App artwork conventions and 2026-10-01 audit

Runtime App Center icons are package-root `icon.png`, optimized 128×128 PNGs.
Use alpha-preserving Lanczos scaling into a transparent square with at most a
108-pixel mark. Check both 128 and 32 pixels against dark and light backgrounds.
Keep recognisable silhouettes, generous margins, no tiny type, and a restrained
charcoal/teal/mint/lime visual family. Do not load full generated source images at
runtime. A shipped icon change requires a version and dated package changelog.

The audit retained Carousel's layered media mark, Bitcoin's clear orange Bitcoin
symbol, and Places' distinctive game-specific doorway pixel art. Debug's thin
chart/grid and Firefly's tiny glowing mark were less readable at launcher size;
their replacements use bold forms. Calculator received a new matching icon.
Terminal, Files and Notepad are Shell companions, not Apps catalog packages, so
this pass does not change them or Shell artwork. There are no separate Settings
packages in this catalog.

Three separate OpenAI built-in image-generation calls produced transparent PNGs.
Each was cropped to alpha bounds at a 16/255 threshold (ignoring almost invisible generator speckles), aspect-preserving scaled to fit 108×108, centered
on transparent 128×128 and saved with PNG optimization. Large generated originals
remain in the Codex generated-images directory, outside installed inventories.
No new runtime dependency was added; Pillow was used only for maintainer processing.
Prompts used on 2026-10-01 follow.

## Calculator

> Use case: logo-brand. Asset: Vitrallis Calculator App Center icon for PocketCHIP. Create one polished original minimalist calculator mark on genuinely transparent background. A deep charcoal rounded square calculator body, warm ivory display showing no text, four large mint green keys in a clear two by two grid with one soft lime accent key. Restrained flat geometric illustration, simple bold silhouette, gentle dimensional edge only, no perspective tilt, centered front view, generous transparent margin. Readable at 32x32 pixels. No text, letters, digits, tiny details, scene or drop shadow. Match a quiet navy/teal/cream/lime first-party device UI.

Saved as `apps/calculator/icon.png`.

## Debug

> Use case: logo-brand. Asset: Vitrallis Debug App Center icon, PocketCHIP 32px display. One original minimalist diagnostic monitor emblem, front view, deep charcoal rounded square monitor housing, bold mint pulse line across a dark teal display, one small lime indicator. Flat geometric illustration with restrained dimensional edge. Centered bold silhouette, generous genuine transparent margin. No text or fine grid, no tiny details, scene or shadow. Quiet teal cream lime family, visually match a first-party calculator with charcoal body and large mint keys.

Saved as `apps/vitrallis-debug/icon.png`.

## Firefly

> Use case: logo-brand. Asset: Firefly Field Vitrallis App Center icon for PocketCHIP 32px display. One original minimalist firefly emblem, a bright lime glowing oval abdomen with mint green simple paired wings and a small charcoal head, subtle contained soft glow, strong recognizable insect silhouette. Flat geometric illustration with restrained dimensional edge, centered symmetrical composition and generous genuinely transparent margin. No text, landscape, frame, fine detail, extra insects or long antennae. Quiet teal lime cream family matching first-party charcoal and mint calculator icon.

Saved as `apps/firefly-field/icon.png`.
