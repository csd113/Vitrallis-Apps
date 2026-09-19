//! Keyboard and touch screens sized for the 480×272 `PocketCHIP` display.
use crate::{
    model::{Order, Settings},
    player::Player,
    render,
    server::{self, Service},
};
use anyhow::Result;
use sdl2::{
    event::{Event, WindowEvent},
    keyboard::{Keycode, Mod},
    pixels::{Color, PixelFormatEnum},
    rect::Rect,
    render::WindowCanvas,
};
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Screen {
    Home,
    Settings,
    Playback,
    Help,
}

pub struct Ui {
    pub screen: Screen,
    pub focus: usize,
    pub selected: usize,
    pub edit: Settings,
    pub player: Option<Player>,
    pub quit: bool,
    pub dirty: bool,
    pub warning: String,
    controls_until: Instant,
    pointer_down: Option<(i32, i32)>,
    controls_focused: bool,
    completed_decoded: u64,
    completed_skipped: u64,
}

impl Ui {
    pub fn new(settings: Settings) -> Self {
        Self {
            screen: Screen::Home,
            focus: 0,
            selected: 0,
            edit: settings,
            player: None,
            quit: false,
            dirty: true,
            warning: String::new(),
            controls_until: Instant::now(),
            pointer_down: None,
            controls_focused: false,
            completed_decoded: 0,
            completed_skipped: 0,
        }
    }

    fn close_player(&mut self) {
        if let Some(player) = self.player.take() {
            self.completed_decoded += player.decoded;
            self.completed_skipped += player.skipped;
        }
    }

    pub fn metrics(&self) -> (u64, u64) {
        let (decoded, skipped) = self
            .player
            .as_ref()
            .map_or((0, 0), |p| (p.decoded, p.skipped));
        (
            self.completed_decoded + decoded,
            self.completed_skipped + skipped,
        )
    }

    pub fn key(&mut self, key: Keycode, shift: bool, service: &Service) -> Result<()> {
        self.dirty = true;
        match (self.screen, key) {
            (_, Keycode::F1) | (Screen::Home, Keycode::H) => {
                self.close_player();
                self.screen = Screen::Help;
            }
            (Screen::Home, Keycode::Escape | Keycode::Q) => self.quit = true,
            (_, Keycode::Escape | Keycode::Backspace) => {
                self.close_player();
                self.screen = Screen::Home;
                self.focus = self.selected;
            }
            (Screen::Help, Keycode::Return | Keycode::Space) => self.screen = Screen::Home,
            (Screen::Home, _) => self.home_key(key, shift, service)?,
            (Screen::Settings, _) => self.settings_key(key, shift, service)?,
            (Screen::Playback, _) => self.playback_key(key, shift),
            _ => (),
        }
        Ok(())
    }

    fn home_key(&mut self, key: Keycode, shift: bool, service: &Service) -> Result<()> {
        let count = server::lock(&service.store)?.library.collections.len();
        match key {
            Keycode::S => {
                self.edit = server::lock(&service.store)?.settings.clone();
                self.focus = 0;
                self.screen = Screen::Settings;
            }
            Keycode::Tab => {
                let size = count + 2;
                self.focus = (self.focus + if shift { size - 1 } else { 1 }) % size;
                if self.focus < count {
                    self.selected = self.focus;
                }
            }
            Keycode::Down => {
                self.selected = (self.selected + 1).min(count.saturating_sub(1));
                self.focus = self.selected;
            }
            Keycode::Up => {
                self.selected = self.selected.saturating_sub(1);
                self.focus = self.selected;
            }
            Keycode::Right => {
                self.selected = (self.selected + 2).min(count.saturating_sub(1));
                self.focus = self.selected;
            }
            Keycode::Left => {
                self.selected = self.selected.saturating_sub(2);
                self.focus = self.selected;
            }
            Keycode::Return | Keycode::Space => match self.focus.cmp(&count) {
                std::cmp::Ordering::Less => self.play(service)?,
                std::cmp::Ordering::Equal => self.home_key(Keycode::S, false, service)?,
                std::cmp::Ordering::Greater => self.quit = true,
            },
            _ => (),
        }
        Ok(())
    }

    pub fn play(&mut self, service: &Service) -> Result<()> {
        let store = server::lock(&service.store)?;
        if let Some(row) = store.library.collections.get(self.selected) {
            self.player = Some(Player::new(
                row.items.clone(),
                store.settings.clone(),
                store.paths.clone(),
                (480, 272),
            ));
            drop(store);
            self.screen = Screen::Playback;
            self.controls_until = Instant::now() + Duration::from_secs(3);
            self.focus = 0;
            self.controls_focused = false;
        }
        Ok(())
    }

    fn settings_key(&mut self, key: Keycode, shift: bool, service: &Service) -> Result<()> {
        match key {
            Keycode::Tab | Keycode::Down => {
                self.focus = (self.focus + if shift { 5 } else { 1 }) % 6;
            }
            Keycode::Up => self.focus = (self.focus + 5) % 6,
            Keycode::Left | Keycode::Right | Keycode::Space | Keycode::Return => {
                let increase = key != Keycode::Left;
                match self.focus {
                    0 => adjust(
                        &mut self.edit.image_seconds,
                        increase,
                        if shift { 60 } else { 1 },
                        3600,
                    ),
                    1 => adjust(&mut self.edit.repeats, increase, 1, 100),
                    2 => {
                        self.edit.order = if self.edit.order == Order::Ordered {
                            Order::Shuffle
                        } else {
                            Order::Ordered
                        }
                    }
                    3 => self.edit.looping = !self.edit.looping,
                    4 if matches!(key, Keycode::Return | Keycode::Space) => {
                        server::lock(&service.store)?.save_settings(self.edit.clone())?;
                        self.screen = Screen::Home;
                        self.focus = 0;
                    }
                    5 if matches!(key, Keycode::Return | Keycode::Space) => {
                        self.screen = Screen::Home;
                        self.focus = 0;
                    }
                    _ => (),
                }
            }
            _ => (),
        }
        Ok(())
    }

    fn playback_key(&mut self, key: Keycode, shift: bool) {
        let Some(player) = &mut self.player else {
            return;
        };
        self.controls_until = Instant::now() + Duration::from_secs(3);
        match key {
            Keycode::Left => player.previous(),
            Keycode::Right => {
                if !player.next() {
                    self.screen = Screen::Home;
                    self.close_player();
                }
            }
            Keycode::Space => player.toggle_pause(Instant::now()),
            Keycode::Tab => {
                self.focus = (self.focus + if shift { 3 } else { 1 }) % 4;
                self.controls_focused = true;
            }
            Keycode::Return => match self.focus {
                0 => player.previous(),
                1 => player.toggle_pause(Instant::now()),
                2 => {
                    if !player.next() {
                        self.screen = Screen::Home;
                        self.close_player();
                    }
                }
                _ => {
                    self.screen = Screen::Home;
                    self.close_player();
                }
            },
            _ => (),
        }
    }

    fn click(&mut self, x: i32, y: i32, service: &Service) -> Result<()> {
        match self.screen {
            Screen::Home => {
                let count = server::lock(&service.store)?.library.collections.len();
                if (108..196).contains(&y) {
                    let row = usize::try_from((y - 108) / 44)?;
                    self.selected = (self.selected / 2 * 2 + row).min(count.saturating_sub(1));
                    self.focus = self.selected;
                    self.play(service)?;
                } else if (204..246).contains(&y) {
                    if x < 170 {
                        self.key(Keycode::S, false, service)?;
                    } else if x < 290 {
                        self.key(Keycode::H, false, service)?;
                    } else if x < 380 {
                        self.key(Keycode::Right, false, service)?;
                    } else {
                        self.quit = true;
                    }
                }
            }
            Screen::Settings => {
                if (36..204).contains(&y) {
                    self.focus = usize::try_from((y - 36) / 42)?;
                    self.key(
                        if x < 240 {
                            Keycode::Left
                        } else {
                            Keycode::Right
                        },
                        false,
                        service,
                    )?;
                } else if (214..256).contains(&y) {
                    self.focus = if x < 240 { 4 } else { 5 };
                    self.key(Keycode::Return, false, service)?;
                }
            }
            Screen::Playback => {
                if y >= 218 && self.controls_visible() {
                    self.focus = usize::try_from(x.max(0) / 120)?.min(3);
                    self.key(Keycode::Return, false, service)?;
                } else {
                    self.controls_until = Instant::now() + Duration::from_secs(3);
                }
            }
            Screen::Help => self.screen = Screen::Home,
        }
        self.dirty = true;
        Ok(())
    }

    fn controls_visible(&self) -> bool {
        self.controls_focused
            || self.player.as_ref().is_some_and(|p| p.paused)
            || Instant::now() < self.controls_until
    }
}

fn adjust(value: &mut u32, increase: bool, step: u32, max: u32) {
    *value = if increase {
        value.saturating_add(step).min(max)
    } else {
        value.saturating_sub(step).max(1)
    };
}

pub fn run(
    service: &Arc<Service>,
    software: bool,
    seconds: Option<u64>,
    play_first: bool,
    screenshot: Option<&std::path::Path>,
) -> Result<()> {
    let sdl = sdl2::init().map_err(anyhow::Error::msg)?;
    let video = sdl.video().map_err(anyhow::Error::msg)?;
    let mut canvas = render::open(&video, software)?;
    let creator = canvas.texture_creator();
    let mut texture = None;
    let mut ui = Ui::new(server::lock(&service.store)?.settings.clone());
    if play_first {
        ui.play(service)?;
    }
    let mut events = sdl.event_pump().map_err(anyhow::Error::msg)?;
    let started = Instant::now();
    let mut last_present = started
        .checked_sub(Duration::from_secs(1))
        .unwrap_or(started);
    let mut last_frame = 0;
    let mut revision = 0;
    let mut last_controls = false;
    let mut presented = 0_u64;
    let mut screenshot_saved = false;
    let mut last_urls = Vec::new();
    while !ui.quit
        && !service.stop.load(Ordering::Relaxed)
        && seconds.is_none_or(|s| started.elapsed() < Duration::from_secs(s))
    {
        events_step(&mut events, &mut ui, service);
        let now = Instant::now();
        if let Some(player) = &mut ui.player
            && !player.tick(now)
        {
            ui.warning.clone_from(&player.warning);
            ui.close_player();
            ui.screen = Screen::Home;
            ui.dirty = true;
        }
        update_texture(&mut ui, &creator, &mut texture, &mut last_frame)?;
        let store_revision = server::lock(&service.store)?.revision;
        let urls = service
            .urls
            .lock()
            .map_err(|_| anyhow::anyhow!("URLs unavailable"))?
            .clone();
        if revision != store_revision || urls != last_urls {
            revision = store_revision;
            last_urls = urls;
            ui.dirty = true;
        }
        let controls = ui.controls_visible();
        if controls != last_controls {
            last_controls = controls;
            ui.dirty = true;
        }
        if ui.dirty && (!software || last_present.elapsed() >= Duration::from_millis(34)) {
            draw(&mut canvas, &ui, service, texture.as_ref())?;
            if !screenshot_saved
                && started.elapsed() >= Duration::from_secs(1)
                && let Some(path) = screenshot
            {
                capture(&canvas, path)?;
                screenshot_saved = true;
            }
            canvas.present();
            presented += 1;
            last_present = Instant::now();
            ui.dirty = false;
        }
        if screenshot.is_some() && !screenshot_saved && started.elapsed() >= Duration::from_secs(1)
        {
            ui.dirty = true;
        }
    }
    let (decoded, skipped) = ui.metrics();
    eprintln!(
        "event=carousel_metrics language=rust elapsed_ms={} presented={presented} decoded={decoded} skipped={skipped}",
        started.elapsed().as_millis()
    );
    Ok(())
}

fn events_step(events: &mut sdl2::EventPump, ui: &mut Ui, service: &Service) {
    let timeout = if ui.screen == Screen::Playback && ui.player.as_ref().is_some_and(|p| !p.paused)
    {
        10
    } else {
        100
    };
    let first = events.wait_event_timeout(timeout);
    let queued: Vec<_> = first.into_iter().chain(events.poll_iter()).collect();
    for event in queued {
        let result = match event {
            Event::Quit { .. } => {
                ui.quit = true;
                Ok(())
            }
            Event::KeyDown {
                keycode: Some(key),
                keymod,
                ..
            } => ui.key(
                key,
                keymod.intersects(Mod::LSHIFTMOD | Mod::RSHIFTMOD),
                service,
            ),
            Event::MouseButtonDown {
                x,
                y,
                mouse_btn: sdl2::mouse::MouseButton::Left,
                ..
            } => {
                ui.pointer_down = Some((x, y));
                Ok(())
            }
            Event::MouseButtonUp {
                x,
                y,
                mouse_btn: sdl2::mouse::MouseButton::Left,
                ..
            } => {
                if ui
                    .pointer_down
                    .take()
                    .is_some_and(|(px, py)| px.abs_diff(x) <= 16 && py.abs_diff(y) <= 16)
                {
                    ui.click(x, y, service)
                } else {
                    Ok(())
                }
            }
            Event::Window {
                win_event:
                    WindowEvent::Exposed | WindowEvent::Resized(_, _) | WindowEvent::SizeChanged(_, _),
                ..
            } => {
                ui.dirty = true;
                Ok(())
            }
            _ => Ok(()),
        };
        if let Err(e) = result {
            ui.warning = e.to_string();
            ui.dirty = true;
        }
    }
}

fn update_texture<'a>(
    ui: &mut Ui,
    creator: &'a sdl2::render::TextureCreator<sdl2::video::WindowContext>,
    texture: &mut Option<sdl2::render::Texture<'a>>,
    last_frame: &mut u64,
) -> Result<()> {
    if let Some(player) = &ui.player {
        if player.current.is_none() && texture.take().is_some() {
            ui.dirty = true;
        }
        if (*last_frame != player.frame_serial || texture.is_none())
            && let Some(frame) = &player.current
        {
            let (w, h) = frame.pixels.dimensions();
            if texture
                .as_ref()
                .is_none_or(|t: &sdl2::render::Texture<'_>| {
                    t.query().width != w || t.query().height != h
                })
            {
                *texture = Some(creator.create_texture_streaming(PixelFormatEnum::RGBA32, w, h)?);
            }
            if let Some(texture) = texture.as_mut() {
                texture.set_blend_mode(sdl2::render::BlendMode::Blend);
                texture.update(None, &frame.pixels, usize::try_from(w)? * 4)?;
            }
            *last_frame = player.frame_serial;
            ui.dirty = true;
        }
    } else {
        *texture = None;
        *last_frame = 0;
    }
    Ok(())
}

fn capture(canvas: &WindowCanvas, path: &std::path::Path) -> Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let (w, h) = canvas.output_size().map_err(anyhow::Error::msg)?;
    let bytes = canvas
        .read_pixels(None, PixelFormatEnum::RGBA32)
        .map_err(anyhow::Error::msg)?;
    let pixels = image::RgbaImage::from_raw(w, h, bytes)
        .ok_or_else(|| anyhow::anyhow!("Invalid screenshot"))?;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    pixels.write_to(&mut file, image::ImageFormat::Png)?;
    Ok(())
}

fn draw(
    canvas: &mut WindowCanvas,
    ui: &Ui,
    service: &Service,
    texture: Option<&sdl2::render::Texture<'_>>,
) -> Result<()> {
    canvas.set_draw_color(Color::RGB(16, 20, 25));
    canvas.clear();
    match ui.screen {
        Screen::Home => home(canvas, ui, service)?,
        Screen::Settings => settings(canvas, ui)?,
        Screen::Help => help(canvas)?,
        Screen::Playback => {
            canvas.set_draw_color(Color::BLACK);
            canvas.clear();
            if let Some(texture) = texture {
                let query = texture.query();
                canvas
                    .copy(
                        texture,
                        None,
                        render::fit((query.width, query.height), (480, 272))?,
                    )
                    .map_err(anyhow::Error::msg)?;
            } else {
                render::text(canvas, "Loading media...", 96, 110, 2, Color::WHITE, 24)?;
            }
            if ui.controls_visible() {
                let paused = ui.player.as_ref().is_some_and(|p| p.paused);
                for (i, label) in [
                    "Prev",
                    if paused { "Resume" } else { "Pause" },
                    "Next",
                    "Back",
                ]
                .iter()
                .enumerate()
                {
                    render::button(
                        canvas,
                        label,
                        Rect::new(i32::try_from(i)? * 120, 222, 116, 42),
                        ui.focus == i,
                    )?;
                }
            }
        }
    }
    Ok(())
}

fn home(canvas: &mut WindowCanvas, ui: &Ui, service: &Service) -> Result<()> {
    render::text(
        canvas,
        "Carousel-Rust",
        12,
        10,
        2,
        Color::RGB(94, 211, 190),
        28,
    )?;
    let urls = service
        .urls
        .lock()
        .map_err(|_| anyhow::anyhow!("URLs unavailable"))?;
    let url = urls.first().map_or(
        if service.port == 0 {
            "LAN server unavailable"
        } else {
            "Starting server..."
        },
        String::as_str,
    );
    render::text(canvas, url, 12, 38, 1, Color::WHITE, 43)?;
    render::text(
        canvas,
        &format!("Code: {}", service.token),
        12,
        57,
        2,
        Color::WHITE,
        21,
    )?;
    render::text(
        canvas,
        "Shared Python photo library",
        12,
        86,
        1,
        Color::RGB(160, 170, 180),
        40,
    )?;
    qr(canvas, url)?;
    drop(urls);
    let store = server::lock(&service.store)?;
    let count = store.library.collections.len();
    for (offset, row) in store
        .library
        .collections
        .iter()
        .enumerate()
        .skip(ui.selected / 2 * 2)
        .take(2)
    {
        render::button(
            canvas,
            &format!("{} ({})", row.name, row.items.len()),
            Rect::new(12, 108 + i32::try_from(offset % 2)? * 44, 456, 40),
            ui.focus == offset,
        )?;
    }
    render::button(
        canvas,
        "Settings",
        Rect::new(12, 204, 152, 40),
        ui.focus == count,
    )?;
    render::button(canvas, "Help", Rect::new(172, 204, 108, 40), false)?;
    render::button(canvas, ">", Rect::new(288, 204, 84, 40), false)?;
    render::button(
        canvas,
        "Exit",
        Rect::new(380, 204, 88, 40),
        ui.focus > count,
    )?;
    let hint = if !ui.warning.is_empty() {
        &ui.warning
    } else if !store.warning.is_empty() {
        &store.warning
    } else {
        "Arrows select | Enter play | S settings | F1 help"
    };
    render::text(canvas, hint, 12, 255, 1, Color::RGB(180, 190, 200), 57)
}

fn qr(canvas: &mut WindowCanvas, url: &str) -> Result<()> {
    if url.starts_with("http://")
        && !url.contains("127.0.0.1")
        && let Ok(code) = qrcode::QrCode::new(url.as_bytes())
    {
        let count = code.width();
        let scale = (96 / (count + 8)).max(1);
        canvas.set_draw_color(Color::WHITE);
        canvas
            .fill_rect(Rect::new(372, 6, 102, 98))
            .map_err(anyhow::Error::msg)?;
        canvas.set_draw_color(Color::BLACK);
        for y in 0..count {
            for x in 0..count {
                if code[(x, y)] == qrcode::Color::Dark {
                    canvas
                        .fill_rect(Rect::new(
                            376 + i32::try_from((x + 4) * scale)?,
                            10 + i32::try_from((y + 4) * scale)?,
                            u32::try_from(scale)?,
                            u32::try_from(scale)?,
                        ))
                        .map_err(anyhow::Error::msg)?;
                }
            }
        }
    }
    Ok(())
}

fn settings(canvas: &mut WindowCanvas, ui: &Ui) -> Result<()> {
    render::text(
        canvas,
        "Playback settings",
        12,
        10,
        2,
        Color::RGB(94, 211, 190),
        28,
    )?;
    let labels = [
        format!("Still seconds: {}", ui.edit.image_seconds),
        format!("Complete plays: {}", ui.edit.repeats),
        format!(
            "Order: {}",
            if ui.edit.order == Order::Ordered {
                "In Order"
            } else {
                "Shuffle"
            }
        ),
        format!(
            "End: {}",
            if ui.edit.looping {
                "Loop Folder"
            } else {
                "Main Menu"
            }
        ),
    ];
    for (index, label) in labels.iter().enumerate() {
        render::button(
            canvas,
            label,
            Rect::new(12, 36 + i32::try_from(index)? * 42, 456, 38),
            ui.focus == index,
        )?;
    }
    render::button(canvas, "Save", Rect::new(12, 214, 220, 42), ui.focus == 4)?;
    render::button(canvas, "Back", Rect::new(244, 214, 224, 42), ui.focus == 5)
}

fn help(canvas: &mut WindowCanvas) -> Result<()> {
    render::text(
        canvas,
        "Keyboard controls",
        12,
        10,
        2,
        Color::RGB(94, 211, 190),
        28,
    )?;
    for (i, line) in [
        "Home: arrows select/page; Enter plays",
        "Tab / Shift+Tab: move focus",
        "S: settings; F1/H: this help; Q: exit",
        "Play: Left previous; Right next",
        "Space: pause/resume; Tab: controls",
        "Enter: activate focused control",
        "Settings: arrows edit; Shift changes by 60",
        "Escape/Backspace: back, discard edits",
        "Escape on Home: orderly exit",
        "Touch/click also works. Enter returns.",
    ]
    .iter()
    .enumerate()
    {
        render::text(
            canvas,
            line,
            12,
            44 + i32::try_from(i)? * 21,
            1,
            Color::WHITE,
            57,
        )?;
    }
    Ok(())
}
