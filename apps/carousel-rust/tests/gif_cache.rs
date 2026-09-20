use super::*;

fn items(count: usize) -> Vec<Item> {
    (0..count)
        .map(|i| Item {
            id: format!("{i:032x}"),
            name: format!("{i}.gif"),
            kind: Kind::Gif,
            size: 1,
        })
        .collect()
}

#[test]
fn rolling_window_releases_past_items_and_keeps_upcoming_frames() {
    let items = items(25);
    let mut cache = Cache::default();
    cache.plan(&items, 0, false);
    assert_eq!(cache.plan.len(), 10);
    for item in &cache.plan {
        cache.entries.push(Entry {
            item: item.clone(),
            value: Prepared::Streaming,
            bytes: 0,
        });
    }
    cache.plan(&items, 7, false);
    assert_eq!(cache.plan.first().map(|i| &i.id), Some(&items[7].id));
    assert_eq!(cache.plan.last().map(|i| &i.id), Some(&items[16].id));
    assert_eq!(cache.entries.len(), 3);
    assert!(cache.get(&items[0]).is_none());
    assert!(cache.get(&items[8]).is_some());
}

#[test]
fn ordered_wrap_and_shuffle_tail_do_not_invent_a_future_order() {
    let mut items = items(12);
    items[10].kind = Kind::Png;
    let mut cache = Cache::default();
    cache.plan(&items, 9, false);
    assert_eq!(cache.plan.len(), 2);
    cache.plan(&items, 9, true);
    assert_eq!(cache.plan.len(), 10);
    assert_eq!(cache.plan[2].id, items[0].id);
    cache.plan(&[], 0, true);
    assert!(cache.plan.is_empty());
}

#[test]
fn foreground_reserves_memory_and_budget_misses_can_retry_after_eviction() {
    let items = items(6);
    let mut cache = Cache::default();
    for item in &items[1..5] {
        cache.entries.push(Entry {
            item: item.clone(),
            value: Prepared::Streaming,
            bytes: GIF_BYTES,
        });
    }
    cache.entries.push(Entry {
        item: items[0].clone(),
        value: Prepared::NoRoom,
        bytes: 0,
    });
    cache.plan(&items, 0, false);
    assert_eq!(cache.used(), TOTAL_BYTES - GIF_BYTES);
    assert!(cache.get(&items[0]).is_none());
    assert!(cache.get(&items[4]).is_none());
    assert!(cache.get(&items[1]).is_some());
}

#[test]
fn changed_item_metadata_invalidates_prepared_entry() {
    let mut items = items(1);
    let mut cache = Cache::default();
    cache.entries.push(Entry {
        item: items[0].clone(),
        value: Prepared::Streaming,
        bytes: 0,
    });
    items[0].size = 2;
    cache.plan(&items, 0, false);
    assert!(cache.get(&items[0]).is_none());
}

struct Fixture(std::path::PathBuf);

#[test]
fn foreground_restarts_a_speculative_job_with_a_reduced_memory_allowance() {
    let items = items(2);
    let mut cache = Cache::default();
    let (_send, output) = mpsc::sync_channel(1);
    let cancel = process::stopped();
    cache.job = Some(Job {
        item: items[1].clone(),
        allowance: GIF_BYTES / 2,
        cancel: Arc::clone(&cancel),
        output,
        thread: None,
    });
    cache.plan(&items, 1, false);
    assert!(cache.job.is_none());
    assert!(cancel.load(Ordering::Relaxed));
    assert!(cache.get(&items[1]).is_none());
}

impl Fixture {
    fn new() -> Result<Self> {
        use std::os::unix::fs::DirBuilderExt;
        let path = std::env::temp_dir()
            .canonicalize()?
            .join(format!("gif-cache-{}", storage::random_id()));
        std::fs::DirBuilder::new().mode(0o700).create(&path)?;
        Ok(Self(path))
    }

    fn gif(&self, size: u32, count: u8) -> Result<(std::path::PathBuf, u64)> {
        use std::os::unix::fs::OpenOptionsExt;
        let path = self.0.join(storage::random_id());
        let file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)?;
        let mut encoder = image::codecs::gif::GifEncoder::new(file);
        for value in 0..count {
            encoder.encode_frame(image::Frame::from_parts(
                image::RgbaImage::from_pixel(size, size, image::Rgba([value, 0, 0, 255])),
                0,
                0,
                image::Delay::from_numer_denom_ms(40, 1),
            ))?;
        }
        drop(encoder);
        let bytes = std::fs::metadata(&path)?.len();
        Ok((path, bytes))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
#[ignore = "requires CAROUSEL_RUST_TEST_BINARY pointing at a freshly built host executable"]
fn real_preparation_validates_complete_frames_budget_and_cancellation() -> Result<()> {
    ensure!(
        std::env::var_os("CAROUSEL_RUST_TEST_BINARY").is_some(),
        "Provide host executable"
    );
    let fixture = Fixture::new()?;
    let (path, size) = fixture.gif(4, 3)?;
    let cancel = AtomicBool::new(false);
    let (value, bytes) = prepare(&path, size, (480, 272), GIF_BYTES, true, &cancel)?;
    let Prepared::Frames(frames) = value else {
        anyhow::bail!("Expected cached frames");
    };
    assert_eq!(frames.len(), 3);
    assert_eq!(bytes, 3 * 4 * 4 * 4);
    assert!(frames.iter().all(|f| f.delay == Duration::from_millis(40)));
    assert_eq!(frames[2].pixels[(0, 0)][0], 2);
    let (value, bytes) = prepare(&path, size, (480, 272), 64, true, &cancel)?;
    assert!(matches!(value, Prepared::NoRoom));
    assert_eq!(bytes, 0);
    let (large, size) = fixture.gif(512, 9)?;
    let (value, bytes) = prepare(&large, size, (480, 272), GIF_BYTES, true, &cancel)?;
    assert!(matches!(value, Prepared::Streaming));
    assert_eq!(bytes, 0);
    cancel.store(true, Ordering::Relaxed);
    assert!(prepare(&large, size, (480, 272), GIF_BYTES, true, &cancel).is_err());
    cancel.store(false, Ordering::Relaxed);
    std::fs::write(&path, b"corrupt")?;
    assert!(prepare(&path, 7, (480, 272), GIF_BYTES, true, &cancel).is_err());
    Ok(())
}
