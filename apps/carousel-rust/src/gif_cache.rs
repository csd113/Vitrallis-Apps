//! Rolling, memory-bounded GIF preparation outside the presentation thread.
use crate::{
    media::{self, Frame},
    model::{Item, Kind},
    process,
    storage::{self, Paths},
};
use anyhow::{Context, Result, ensure};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread::JoinHandle,
    time::{Duration, Instant},
};

pub const WINDOW: usize = 10;
const TOTAL_BYTES: usize = 32 * 1024 * 1024;
const GIF_BYTES: usize = 8 * 1024 * 1024;
pub type Animation = Arc<Vec<Arc<Frame>>>;

#[derive(Clone)]
pub enum Prepared {
    Frames(Animation),
    Streaming,
    NoRoom,
}

struct Entry {
    item: Item,
    value: Prepared,
    bytes: usize,
}

struct Job {
    item: Item,
    allowance: usize,
    cancel: Arc<AtomicBool>,
    output: mpsc::Receiver<(Prepared, usize)>,
    thread: Option<JoinHandle<()>>,
}

impl Drop for Job {
    fn drop(&mut self) {
        self.cancel.store(true, Ordering::Relaxed);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

#[derive(Default)]
pub struct Cache {
    plan: Vec<Item>,
    entries: Vec<Entry>,
    job: Option<Job>,
    current: Option<String>,
}

fn same(left: &Item, right: &Item) -> bool {
    left.id == right.id && left.size == right.size && left.kind == right.kind
}

impl Cache {
    pub fn plan(&mut self, items: &[Item], index: usize, wrap: bool) {
        self.current = items
            .get(index)
            .filter(|i| i.kind == Kind::Gif)
            .map(|i| i.id.clone());
        self.plan.clear();
        for offset in 0..items.len() {
            let next = index + offset;
            if next >= items.len() && !wrap {
                break;
            }
            let item = &items[next % items.len()];
            if item.kind == Kind::Gif && !self.plan.iter().any(|i| same(i, item)) {
                self.plan.push(item.clone());
                if self.plan.len() == WINDOW {
                    break;
                }
            }
        }
        self.entries.retain(|entry| {
            self.plan.iter().any(|i| same(i, &entry.item))
                && !matches!(entry.value, Prepared::NoRoom)
        });
        let foreground_missing = self
            .current
            .as_ref()
            .is_some_and(|id| !self.entries.iter().any(|e| &e.item.id == id));
        if self.job.as_ref().is_some_and(|job| {
            !self.plan.iter().any(|i| same(i, &job.item))
                || (foreground_missing
                    && (self.current.as_ref() != Some(&job.item.id) || job.allowance < GIF_BYTES))
        }) {
            self.job = None;
        }
        // Give an uncached current GIF a full per-animation allowance, evicting
        // the most distant prepared items first. The old player is already gone.
        if foreground_missing {
            while self.used() > TOTAL_BYTES - GIF_BYTES {
                let Some(position) = self.plan.iter().rev().find_map(|item| {
                    self.entries
                        .iter()
                        .position(|e| same(item, &e.item) && e.bytes > 0)
                }) else {
                    break;
                };
                self.entries.remove(position);
            }
        }
    }

    fn used(&self) -> usize {
        self.entries.iter().map(|e| e.bytes).sum()
    }

    pub fn get(&self, item: &Item) -> Option<Prepared> {
        self.entries
            .iter()
            .find(|e| same(&e.item, item))
            .map(|e| e.value.clone())
    }

    pub fn tick(&mut self, paths: &Paths, size: (u32, u32)) {
        if let Some(job) = &self.job {
            match job.output.try_recv() {
                Ok((value, bytes)) => self.entries.push(Entry {
                    item: job.item.clone(),
                    value,
                    bytes,
                }),
                Err(mpsc::TryRecvError::Empty) => return,
                Err(mpsc::TryRecvError::Disconnected) => self.entries.push(Entry {
                    item: job.item.clone(),
                    value: Prepared::Streaming,
                    bytes: 0,
                }),
            }
            self.job = None;
        }
        let Some(item) = self.plan.iter().find(|i| self.get(i).is_none()).cloned() else {
            return;
        };
        let allowance = GIF_BYTES.min(TOTAL_BYTES.saturating_sub(self.used()));
        if allowance == 0 {
            self.entries.push(Entry {
                item,
                value: Prepared::NoRoom,
                bytes: 0,
            });
            return;
        }
        let foreground = self.current.as_ref() == Some(&item.id);
        let path = paths.media.join(&item.id);
        let expected_size = item.size;
        let cancel = process::stopped();
        let stop = Arc::clone(&cancel);
        let (send, output) = mpsc::sync_channel(1);
        let thread = std::thread::spawn(move || {
            let result = prepare(&path, expected_size, size, allowance, foreground, &stop)
                .unwrap_or((Prepared::Streaming, 0));
            let _ = send.send(result);
        });
        self.job = Some(Job {
            item,
            allowance,
            cancel,
            output,
            thread: Some(thread),
        });
    }
}

fn prepare(
    path: &std::path::Path,
    expected_size: u64,
    size: (u32, u32),
    allowance: usize,
    foreground: bool,
    cancel: &AtomicBool,
) -> Result<(Prepared, usize)> {
    let file = storage::regular(path, storage::MAX_UPLOAD)?;
    ensure!(
        file.metadata()?.len() == expected_size,
        "Media size no longer matches the library"
    );
    let mut command = media::command(file, "--decode", size, 1)?;
    command.arg(serde_json::to_string(&Kind::Gif)?);
    let mut child = process::spawn(&mut command)?;
    let mut output = child.0.stdout.take().context("Missing decoder output")?;
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut frames = Vec::new();
    let mut bytes = 0;
    while let Some(frame) = media::read_frame(&mut output, cancel, deadline)? {
        bytes += frame.pixels.len();
        if bytes > allowance {
            return Ok((
                if allowance < GIF_BYTES {
                    Prepared::NoRoom
                } else {
                    Prepared::Streaming
                },
                0,
            ));
        }
        frames.push(Arc::new(frame));
        if !foreground {
            std::thread::sleep(Duration::from_millis(10));
        }
    }
    loop {
        ensure!(
            !cancel.load(Ordering::Relaxed) && Instant::now() < deadline,
            "Preparation cancelled/timed out"
        );
        if let Some(status) = child.0.try_wait()? {
            ensure!(
                status.success() && !frames.is_empty(),
                "GIF preparation failed"
            );
            return Ok((Prepared::Frames(Arc::new(frames)), bytes));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[cfg(test)]
#[path = "../tests/gif_cache.rs"]
mod tests;
