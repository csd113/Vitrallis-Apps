//! Verify actual backbuffer pixels without a window or a display server.
use super::*;
use crate::{media::Frame, model::Store, tests::Fixture};
use anyhow::Context;
use image::{Rgba, RgbaImage};
use sdl2::{render::SurfaceCanvas, surface::Surface};
use std::sync::Mutex;

fn canvas() -> Result<SurfaceCanvas<'static>> {
    Surface::new(480, 272, PixelFormatEnum::RGBA32)
        .map_err(anyhow::Error::msg)?
        .into_canvas()
        .map_err(anyhow::Error::msg)
}

fn pixels(canvas: &SurfaceCanvas<'_>) -> Result<RgbaImage> {
    let bytes = canvas
        .read_pixels(None, PixelFormatEnum::RGBA32)
        .map_err(anyhow::Error::msg)?;
    RgbaImage::from_raw(480, 272, bytes).context("Invalid backbuffer")
}

fn bounds(pixels: &RgbaImage, color: [u8; 4]) -> Result<Rect> {
    let mut bounds = None::<Rect>;
    for (x, y, pixel) in pixels.enumerate_pixels() {
        if pixel.0 == color {
            let point = Rect::new(i32::try_from(x)?, i32::try_from(y)?, 1, 1);
            bounds = Some(bounds.map_or(point, |rect| rect.union(point)));
        }
    }
    bounds.context("Expected visible pixels")
}

#[test]
fn button_ink_is_centered_with_descenders_narrow_glyphs_and_truncation() -> Result<()> {
    let mut canvas = canvas()?;
    for (label, rect) in [
        ("Settings", Rect::new(12, 204, 152, 40)),
        (">", Rect::new(288, 204, 84, 40)),
        ("Resume", Rect::new(120, 222, 116, 42)),
        (
            "A very long collection name é ☃",
            Rect::new(12, 108, 456, 40),
        ),
        ("é ☃ gy", Rect::new(12, 108, 456, 40)),
    ] {
        canvas.set_draw_color(Color::BLACK);
        canvas.clear();
        render::button(&mut canvas, label, rect, false)?;
        let ink = bounds(&pixels(&canvas)?, [240, 242, 238, 255])?;
        assert!(rect.contains_rect(ink));
        assert!((ink.left() - rect.left()).abs_diff(rect.right() - ink.right()) <= 1);
        assert!((ink.top() - rect.top()).abs_diff(rect.bottom() - ink.bottom()) <= 1);
    }
    Ok(())
}

#[test]
fn qr_has_square_pixels_equal_quiet_zones_and_fits_the_header() -> Result<()> {
    let mut canvas = canvas()?;
    for (url, side, module) in [
        ("http://192.168.81.1:8765", 99, 3),
        ("http://192.168.100.100:65535", 74, 2),
    ] {
        canvas.set_draw_color(Color::RGB(16, 20, 25));
        canvas.clear();
        qr(&mut canvas, url)?;
        let image = pixels(&canvas)?;
        let paper = bounds(&image, [255; 4])?;
        let ink = bounds(&image, [0, 0, 0, 255])?;
        assert_eq!((paper.width(), paper.height()), (side, side));
        assert!(Rect::new(368, 4, 100, 100).contains_rect(paper));
        assert_eq!(ink.width(), ink.height());
        assert_eq!(ink.left() - paper.left(), module * 4);
        assert_eq!(paper.right() - ink.right(), module * 4);
        assert_eq!(ink.top() - paper.top(), module * 4);
        assert_eq!(paper.bottom() - ink.bottom(), module * 4);
        // Every module occupies a complete square, without interpolation.
        for y in (ink.top()..ink.bottom()).step_by(usize::try_from(module)?) {
            for x in (ink.left()..ink.right()).step_by(usize::try_from(module)?) {
                let expected = image[(u32::try_from(x)?, u32::try_from(y)?)];
                for dy in 0..module {
                    for dx in 0..module {
                        assert_eq!(
                            image[(u32::try_from(x + dx)?, u32::try_from(y + dy)?)],
                            expected
                        );
                    }
                }
            }
        }
    }
    Ok(())
}

fn snapshot(canvas: &SurfaceCanvas<'_>, name: &str) -> Result<()> {
    if let Some(directory) = std::env::var_os("CAROUSEL_RUST_SCREENSHOT_DIR") {
        let mut file = std::fs::File::create_new(std::path::Path::new(&directory).join(name))?;
        pixels(canvas)?.write_to(&mut file, image::ImageFormat::Png)?;
    }
    Ok(())
}

#[test]
fn transitions_retain_pixels_until_replacement_and_clear_on_exit() -> Result<()> {
    let fixture = Fixture::new()?;
    let paths = fixture.paths()?;
    let shared = Arc::new(Mutex::new(Store::open(paths.clone())?));
    let server = server::Server::start(shared, crate::process::stopped(), "127.0.0.1", 0)?;
    let mut service = Arc::clone(&server.service);
    drop(server);
    let service = Arc::get_mut(&mut service).context("Fixture service still shared")?;
    service.token = "abc123".into();
    *service
        .urls
        .get_mut()
        .map_err(|_| anyhow::anyhow!("URLs poisoned"))? = vec!["http://192.168.81.1:8765".into()];
    let mut canvas = canvas()?;
    let creator = canvas.texture_creator();
    let mut texture = None;
    let mut last_frame = 0;
    let mut ui = Ui::new(Settings::default());
    for (screen, name) in [
        (Screen::Home, "home.png"),
        (Screen::Settings, "settings.png"),
        (Screen::Help, "help.png"),
    ] {
        ui.screen = screen;
        draw(&mut canvas, &ui, service, None)?;
        snapshot(&canvas, name)?;
    }
    let items = (0..2)
        .map(|id| crate::model::Item {
            id: format!("{id:032x}"),
            name: "Pending.gif".into(),
            kind: crate::model::Kind::Gif,
            size: 1,
        })
        .collect();
    ui.player = Some(Player::new(items, Settings::default(), paths, (480, 272)));
    ui.screen = Screen::Playback;
    ui.controls_until = Instant::now();
    update_texture(&mut ui, &creator, &mut texture, &mut last_frame)?;
    assert!(texture.is_none());
    let player = ui.player.as_mut().context("Missing player")?;
    player.current = Some(Arc::new(Frame {
        pixels: RgbaImage::from_pixel(480, 272, Rgba([180, 40, 20, 255])),
        delay: Duration::from_millis(100),
    }));
    player.frame_serial = 1;
    update_texture(&mut ui, &creator, &mut texture, &mut last_frame)?;
    draw(&mut canvas, &ui, service, texture.as_ref())?;
    let previous = pixels(&canvas)?;
    for forward in [true, false, true] {
        let player = ui.player.as_mut().context("Missing player")?;
        if forward {
            assert!(player.next());
        } else {
            player.previous();
        }
        assert!(player.current.is_none());
        ui.dirty = false;
        update_texture(&mut ui, &creator, &mut texture, &mut last_frame)?;
        assert!(
            !ui.dirty,
            "Waiting for a decoder must not trigger extra presentations"
        );
        draw(&mut canvas, &ui, service, texture.as_ref())?;
        assert_eq!(
            pixels(&canvas)?,
            previous,
            "Transition must not flash loading text or blank pixels"
        );
    }
    let player = ui.player.as_mut().context("Missing player")?;
    player.current = Some(Arc::new(Frame {
        pixels: RgbaImage::from_pixel(40, 40, Rgba([20, 140, 100, 255])),
        delay: Duration::from_millis(100),
    }));
    player.frame_serial += 1;
    update_texture(&mut ui, &creator, &mut texture, &mut last_frame)?;
    draw(&mut canvas, &ui, service, texture.as_ref())?;
    let replacement = pixels(&canvas)?;
    assert_eq!(replacement[(240, 136)].0, [20, 140, 100, 255]);
    assert_eq!(replacement[(0, 0)].0, [0, 0, 0, 255]);
    ui.controls_focused = true;
    draw(&mut canvas, &ui, service, texture.as_ref())?;
    snapshot(&canvas, "playback.png")?;
    ui.key(Keycode::Escape, false, service)?;
    update_texture(&mut ui, &creator, &mut texture, &mut last_frame)?;
    assert!(texture.is_none());
    assert_eq!(last_frame, 0);
    Ok(())
}
