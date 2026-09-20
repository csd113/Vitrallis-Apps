//! Stable playlist snapshots, bounded decoding, absolute media deadlines.
use crate::{
    gif_cache::{Animation, Cache, Prepared},
    media::{self, Frame},
    model::{Item, Kind, Order, Settings},
    process,
    storage::{self, Paths},
};
use anyhow::{Context, Result};
use rand::seq::SliceRandom;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
    mpsc::{self, Receiver, TrySendError},
};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

struct Decoder {
    frames: Receiver<Result<Arc<Frame>>>,
    cancel: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl Decoder {
    fn start(paths: &Paths, item: &Item, size: (u32, u32), repeats: u32) -> Result<Self> {
        let file = storage::regular(&paths.media.join(&item.id), storage::MAX_UPLOAD)?;
        anyhow::ensure!(
            file.metadata()?.len() == item.size,
            "Media size no longer matches the library"
        );
        let mut command = media::command(file, "--decode", size, repeats)?;
        command.arg(serde_json::to_string(&item.kind)?);
        let mut child = process::spawn(&mut command)?;
        let mut output = child.0.stdout.take().context("Missing decoder output")?;
        let cancel = process::stopped();
        let stop = Arc::clone(&cancel);
        let (send, frames) = mpsc::sync_channel(2);
        let thread = std::thread::spawn(move || {
            let send_frame = |mut frame| {
                loop {
                    if stop.load(Ordering::Relaxed) {
                        return false;
                    }
                    match send.try_send(frame) {
                        Ok(()) => return true,
                        Err(TrySendError::Disconnected(_)) => return false,
                        Err(TrySendError::Full(value)) => {
                            frame = value;
                            std::thread::sleep(Duration::from_millis(5));
                        }
                    }
                }
            };
            loop {
                match media::read_frame(
                    &mut output,
                    &stop,
                    Instant::now() + Duration::from_secs(15),
                ) {
                    Ok(Some(frame)) => {
                        if !send_frame(Ok(Arc::new(frame))) {
                            break;
                        }
                    }
                    Ok(None) => {
                        let deadline = Instant::now() + Duration::from_secs(2);
                        loop {
                            match child.0.try_wait() {
                                Ok(Some(status)) => {
                                    if !status.success() {
                                        send_frame(Err(anyhow::anyhow!("Media decoding failed")));
                                    }
                                    break;
                                }
                                Ok(None)
                                    if !stop.load(Ordering::Relaxed)
                                        && Instant::now() < deadline =>
                                {
                                    std::thread::sleep(Duration::from_millis(10));
                                }
                                _ => {
                                    send_frame(Err(anyhow::anyhow!("Decoder did not exit")));
                                    break;
                                }
                            }
                        }
                        break;
                    }
                    Err(e) => {
                        send_frame(Err(e));
                        break;
                    }
                }
            }
        });
        Ok(Self {
            frames,
            cancel,
            thread: Some(thread),
        })
    }

    fn cached(paths: &Paths, item: &Item, animation: Animation, repeats: u32) -> Result<Self> {
        // Cached pixels do not authorize playback of a removed/replaced item.
        let file = storage::regular(&paths.media.join(&item.id), storage::MAX_UPLOAD)?;
        anyhow::ensure!(
            file.metadata()?.len() == item.size,
            "Media size no longer matches the library"
        );
        let cancel = process::stopped();
        let stop = Arc::clone(&cancel);
        let (send, frames) = mpsc::sync_channel(2);
        let thread = std::thread::spawn(move || {
            for _ in 0..repeats {
                for frame in animation.iter() {
                    let mut value = Ok(Arc::clone(frame));
                    loop {
                        if stop.load(Ordering::Relaxed) {
                            return;
                        }
                        match send.try_send(value) {
                            Ok(()) => break,
                            Err(TrySendError::Disconnected(_)) => return,
                            Err(TrySendError::Full(frame)) => {
                                value = frame;
                                std::thread::sleep(Duration::from_millis(5));
                            }
                        }
                    }
                }
            }
        });
        Ok(Self {
            frames,
            cancel,
            thread: Some(thread),
        })
    }
}

impl Drop for Decoder {
    fn drop(&mut self) {
        self.cancel.store(true, Ordering::Relaxed);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

pub struct Player {
    pub items: Vec<Item>,
    pub index: usize,
    pub paused: bool,
    pub current: Option<Arc<Frame>>,
    pub warning: String,
    pub frame_serial: u64,
    pub decoded: u64,
    pub skipped: u64,
    settings: Settings,
    paths: Paths,
    decoder: Option<Decoder>,
    pending: Option<Arc<Frame>>,
    deadline: Option<Instant>,
    paused_at: Option<Instant>,
    size: (u32, u32),
    failures: usize,
    cache: Cache,
    preparing: bool,
}

impl Player {
    pub fn new(mut items: Vec<Item>, settings: Settings, paths: Paths, size: (u32, u32)) -> Self {
        if settings.order == Order::Shuffle {
            shuffle(&mut items, None);
        }
        let mut player = Self {
            items,
            index: 0,
            paused: false,
            current: None,
            warning: String::new(),
            frame_serial: 0,
            decoded: 0,
            skipped: 0,
            settings,
            paths,
            decoder: None,
            pending: None,
            deadline: None,
            paused_at: None,
            size,
            failures: 0,
            cache: Cache::default(),
            preparing: false,
        };
        player.start();
        player
    }

    fn start(&mut self) {
        self.decoder = None;
        self.current = None;
        self.pending = None;
        self.deadline = None;
        self.paused = false;
        self.paused_at = None;
        self.cache.plan(
            &self.items,
            self.index,
            self.settings.looping && self.settings.order == Order::Ordered,
        );
        self.preparing = false;
        if let Some(item) = self.items.get(self.index) {
            if item.kind == Kind::Gif {
                self.preparing = true;
                return;
            }
            match Decoder::start(&self.paths, item, self.size, self.settings.repeats) {
                Ok(decoder) => self.decoder = Some(decoder),
                Err(e) => self.warning = e.to_string(),
            }
        }
    }

    pub fn toggle_pause(&mut self, now: Instant) {
        self.paused = !self.paused;
        if self.paused {
            self.paused_at = Some(now);
        } else if let Some(start) = self.paused_at.take()
            && let Some(deadline) = &mut self.deadline
        {
            *deadline += now.saturating_duration_since(start);
        }
    }

    pub fn previous(&mut self) {
        self.index = self.index.saturating_sub(1);
        self.failures = 0;
        self.start();
    }

    pub fn next(&mut self) -> bool {
        self.index += 1;
        if self.index >= self.items.len() {
            if !self.settings.looping || self.items.is_empty() {
                return false;
            }
            let previous = self.items.last().map(|i| i.id.clone());
            if self.settings.order == Order::Shuffle {
                shuffle(&mut self.items, previous.as_deref());
            }
            self.index = 0;
        }
        self.start();
        true
    }

    pub fn tick(&mut self, now: Instant) -> bool {
        if self.items.is_empty() || self.failures >= self.items.len() {
            self.warning = "No playable media in this collection".into();
            return false;
        }
        self.cache.tick(&self.paths, self.size);
        if self.preparing {
            let item = &self.items[self.index];
            let Some(prepared) = self.cache.get(item) else {
                return true;
            };
            let decoder = match prepared {
                Prepared::Frames(frames) => {
                    Decoder::cached(&self.paths, item, frames, self.settings.repeats)
                }
                Prepared::Streaming | Prepared::NoRoom => {
                    Decoder::start(&self.paths, item, self.size, self.settings.repeats)
                }
            };
            self.preparing = false;
            match decoder {
                Ok(decoder) => self.decoder = Some(decoder),
                Err(e) => self.warning = e.to_string(),
            }
        }
        if self.paused {
            return true;
        }
        if self.decoder.is_none() {
            return self.failed_next();
        }
        // At most three queued frames per event-loop turn; expired frames retain
        // their absolute deadlines and are skipped rather than slowing playback.
        for _ in 0..3 {
            if self.pending.is_none() {
                let result = self.decoder.as_ref().map(|d| d.frames.try_recv());
                match result {
                    Some(Ok(Ok(frame))) => {
                        self.pending = Some(frame);
                        self.decoded += 1;
                    }
                    Some(Ok(Err(e))) => {
                        self.warning = e.to_string();
                        return self.failed_next();
                    }
                    Some(Err(mpsc::TryRecvError::Disconnected))
                        if self.deadline.is_none_or(|d| now >= d) =>
                    {
                        return self.next();
                    }
                    _ => (),
                }
            }
            if self.deadline.is_some_and(|d| now < d) {
                break;
            }
            let Some(frame) = self.pending.take() else {
                break;
            };
            let delay = if matches!(self.items[self.index].kind, Kind::Gif | Kind::Webm) {
                frame.delay
            } else {
                Duration::from_secs(u64::from(self.settings.image_seconds))
            };
            let deadline = self.deadline.unwrap_or(now) + delay;
            self.deadline = Some(deadline);
            self.failures = 0;
            if deadline <= now {
                self.skipped += 1;
            }
            self.current = Some(frame);
            self.frame_serial += 1;
        }
        true
    }

    fn failed_next(&mut self) -> bool {
        self.failures += 1;
        if self.failures >= self.items.len() {
            return false;
        }
        self.next()
    }
}

pub fn shuffle(items: &mut [Item], previous: Option<&str>) {
    items.shuffle(&mut rand::rng());
    if items.len() > 1 && previous.is_some_and(|id| items[0].id == id) {
        items.swap(0, 1);
    }
}

#[cfg(test)]
#[path = "../tests/player.rs"]
mod tests;
