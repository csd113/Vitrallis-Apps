//! One complete SDL backbuffer presentation per changed frame.
use anyhow::{Result, bail, ensure};
use font8x8::UnicodeFonts;
use sdl2::{
    pixels::Color,
    rect::Rect,
    render::{Canvas, RenderTarget, WindowCanvas},
};

pub fn open(video: &sdl2::VideoSubsystem, software: bool) -> Result<WindowCanvas> {
    sdl2::hint::set("SDL_RENDER_SCALE_QUALITY", "linear");
    sdl2::hint::set("SDL_VIDEO_X11_WMCLASS", "io.vitrallis.carouselrust");
    sdl2::hint::set("SDL_APP_NAME", "Carousel-Rust");
    let mut failures = Vec::new();
    for (index, driver) in sdl2::render::drivers().enumerate() {
        if driver.flags & 6 != 6 {
            continue;
        } // ACCELERATED | PRESENTVSYNC
        let window = video
            .window("Carousel-Rust", 480, 272)
            .position_centered()
            .resizable()
            .build()?;
        match window
            .into_canvas()
            .index(u32::try_from(index)?)
            .accelerated()
            .present_vsync()
            .build()
        {
            Ok(mut canvas) => {
                let info = canvas.info();
                if info.flags & 6 != 6 {
                    failures.push(format!("{} omitted required flags", info.name));
                    continue;
                }
                match hardware_name(video, info.name) {
                    Ok(name) => {
                        #[cfg(target_os = "linux")]
                        if !software && !crate::compositor::present(canvas.window())? {
                            failures.push("X11 compositor is not running; restore the platform VSync compositor".into());
                            continue;
                        }
                        canvas.set_logical_size(480, 272)?;
                        eprintln!(
                            "event=media_renderer language=rust backend={} gpu={name:?} accelerated=true vsync_requested=true physical_scanout=unverified",
                            info.name
                        );
                        return Ok(canvas);
                    }
                    Err(e) => failures.push(e.to_string()),
                }
            }
            Err(e) => failures.push(format!("{}: {e}", driver.name)),
        }
    }
    if software {
        let window = video
            .window("Carousel-Rust — software development mode", 480, 272)
            .resizable()
            .build()?;
        let mut canvas = window.into_canvas().software().build()?;
        canvas.set_logical_size(480, 272)?;
        eprintln!(
            "event=media_renderer language=rust backend=software accelerated=false vsync=false cap_fps=30"
        );
        return Ok(canvas);
    }
    bail!(
        "No verified accelerated VSync renderer: {}. Check SDL/EGL/GLES and the platform compositor.",
        failures.join("; ")
    )
}

fn hardware_name(video: &sdl2::VideoSubsystem, backend: &str) -> Result<String> {
    if backend == "metal" {
        return Ok("Metal".into());
    }
    ensure!(
        backend.starts_with("opengl"),
        "Unverified hardware backend {backend}"
    );
    let pointer = video.gl_get_proc_address("glGetString");
    ensure!(!pointer.is_null(), "GL renderer query unavailable");
    // SAFETY: SDL resolved the active context's standard glGetString entry point.
    let get_string: unsafe extern "C" fn(u32) -> *const std::ffi::c_char =
        unsafe { std::mem::transmute(pointer) };
    // SAFETY: GL_RENDERER is valid for the current SDL-created context.
    let value = unsafe { get_string(0x1f01) };
    ensure!(!value.is_null(), "GL renderer unavailable");
    // SAFETY: GL owns a NUL-terminated string until context destruction.
    let name = unsafe { std::ffi::CStr::from_ptr(value) }
        .to_string_lossy()
        .into_owned();
    let lower = name.to_lowercase();
    ensure!(
        !["llvmpipe", "softpipe", "swrast", "software", "swiftshader"]
            .iter()
            .any(|v| lower.contains(v))
            && [
                "mali",
                "lima",
                "panfrost",
                "apple",
                "intel",
                "nvidia",
                "radeon",
                "amd",
                "vivante",
                "adreno",
                "videocore"
            ]
            .iter()
            .any(|v| lower.contains(v)),
        "Unverified hardware renderer {name}"
    );
    Ok(name)
}

fn glyph(ch: char) -> [u8; 8] {
    font8x8::BASIC_FONTS
        .get(ch)
        .or_else(|| font8x8::LATIN_FONTS.get(ch))
        .unwrap_or([0x7e, 0x42, 0x02, 0x0c, 0x10, 0, 0x10, 0])
}

pub fn text<T: RenderTarget>(
    canvas: &mut Canvas<T>,
    value: &str,
    x: i32,
    y: i32,
    scale: u32,
    color: Color,
    maximum: usize,
) -> Result<()> {
    canvas.set_draw_color(color);
    let step = i32::try_from(scale)?;
    for (index, ch) in value.chars().take(maximum).enumerate() {
        let bitmap = glyph(ch);
        let offset = i32::try_from(index)? * 8 * step;
        for (row, bits) in bitmap.iter().enumerate() {
            for column in 0..8 {
                if bits & (1 << column) != 0 {
                    canvas
                        .fill_rect(Rect::new(
                            x + offset + column * step,
                            y + i32::try_from(row)? * step,
                            scale,
                            scale,
                        ))
                        .map_err(anyhow::Error::msg)?;
                }
            }
        }
    }
    Ok(())
}

pub fn centered_text<T: RenderTarget>(
    canvas: &mut Canvas<T>,
    value: &str,
    rect: Rect,
    scale: u32,
    color: Color,
) -> Result<()> {
    ensure!(
        scale > 0 && scale <= rect.height() / 8,
        "Invalid text scale"
    );
    let maximum = usize::try_from(rect.width() / (8 * scale))?;
    // Center visible ink, including narrow glyphs and descenders, rather than
    // the font's padded cells. Measure the same truncated text that is drawn.
    let mut bounds = None::<Rect>;
    for (index, ch) in value.chars().take(maximum).enumerate() {
        for (row, bits) in glyph(ch).iter().enumerate() {
            for column in 0..8 {
                if bits & (1 << column) != 0 {
                    let pixel = Rect::new(
                        i32::try_from(index * 8 + column)?,
                        i32::try_from(row)?,
                        1,
                        1,
                    );
                    bounds = Some(bounds.map_or(pixel, |b| b.union(pixel)));
                }
            }
        }
    }
    if let Some(bounds) = bounds {
        text(
            canvas,
            value,
            rect.x() + i32::try_from((rect.width() - bounds.width() * scale) / 2)?
                - bounds.x() * i32::try_from(scale)?,
            rect.y() + i32::try_from((rect.height() - bounds.height() * scale) / 2)?
                - bounds.y() * i32::try_from(scale)?,
            scale,
            color,
            maximum,
        )?;
    }
    Ok(())
}

pub fn button<T: RenderTarget>(
    canvas: &mut Canvas<T>,
    label: &str,
    rect: Rect,
    focused: bool,
) -> Result<()> {
    canvas.set_draw_color(if focused {
        Color::RGB(42, 111, 115)
    } else {
        Color::RGB(35, 42, 50)
    });
    canvas.fill_rect(rect).map_err(anyhow::Error::msg)?;
    centered_text(
        canvas,
        label,
        Rect::new(rect.x() + 8, rect.y(), rect.width() - 16, rect.height()),
        2,
        Color::RGB(240, 242, 238),
    )
}

pub fn fit(source: (u32, u32), destination: (u32, u32)) -> Result<Rect> {
    ensure!(
        source.0 > 0 && source.1 > 0 && destination.0 > 0 && destination.1 > 0,
        "Invalid frame size"
    );
    let (width, height) = if u64::from(source.0) * u64::from(destination.1)
        > u64::from(source.1) * u64::from(destination.0)
    {
        (
            destination.0,
            u32::try_from(u64::from(source.1) * u64::from(destination.0) / u64::from(source.0))?
                .max(1),
        )
    } else {
        (
            u32::try_from(u64::from(source.0) * u64::from(destination.1) / u64::from(source.1))?
                .max(1),
            destination.1,
        )
    };
    Ok(Rect::new(
        i32::try_from((destination.0 - width) / 2)?,
        i32::try_from((destination.1 - height) / 2)?,
        width,
        height,
    ))
}
