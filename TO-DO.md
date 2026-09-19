- [x] Debug 0.2.1: discover GPU devfreq devices and average devfreq_monitor load.
- [x] Media Carousel 0.1.4: add GPU GIF presentation and correct animation timing.

- [x] Add a Vitrallis app requirement that all graphical apps must use double buffering and synchronize frame presentation to VSync/vblank to prevent screen tearing, rather than drawing directly to the visible buffer.
- [x] Verify devfreq trace permissions, GPU playback speed and overlay behavior on physical Lima/Mali hardware.
- [x] experimental Rust app support


-- Debug app
- [x] debug menu should have cpu and gpu usage stats overlaying the gpu render test pulse so users can see if they are actually being used, app needs keyboard support updated
- [x] Debug menu needs to set proper gpu frequency read permissions upon install

-- Firefly app
- [x] firefly app needs serious backend optimization, even having the menu tab open drops FPS to very low

-- Media carousel app
- [x] vitrallis-media-carousel needs a refinement and performance polish run, including better design of upload page, qr code on device to open upload page, better gif performance, try to find why screen tearing occurs so often, multiple uploads in parallel
- [x] allow downlaoding folder from web interface
- [x] show thumbnails on web interface
- [x] one click install ffmpeg with webm and webp support with proper checker to make sure they are present

Implementation and validation details, including remaining device-installation limits: [2026-09-19 verification report](docs/verification/platform-app-refinements-2026-09-19/README.md).
