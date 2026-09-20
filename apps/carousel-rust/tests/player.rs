//! Deterministic media-clock tests using the real bounded frame consumer.
use super::*;
use crate::model::{Kind, Order};
use image::{Rgba, RgbaImage};

fn scripted() -> (Player, mpsc::SyncSender<Result<Arc<Frame>>>, Instant) {
    let now = Instant::now();
    let (send, frames) = mpsc::sync_channel(2);
    let item = Item {
        id: "0".repeat(32),
        name: "animated.gif".into(),
        kind: Kind::Gif,
        size: 1,
    };
    let paths = Paths {
        config: "/unused".into(),
        data: "/unused".into(),
        media: "/unused".into(),
        uploads: "/unused".into(),
    };
    let decoder = Decoder {
        frames,
        cancel: process::stopped(),
        thread: None,
    };
    (
        Player {
            items: vec![item],
            index: 0,
            paused: false,
            current: None,
            warning: String::new(),
            frame_serial: 0,
            decoded: 0,
            skipped: 0,
            settings: Settings {
                looping: false,
                order: Order::Ordered,
                ..Settings::default()
            },
            paths,
            decoder: Some(decoder),
            pending: None,
            deadline: None,
            paused_at: None,
            size: (480, 272),
            failures: 0,
            cache: Cache::default(),
            preparing: false,
        },
        send,
        now,
    )
}
fn frame(value: u8) -> Arc<Frame> {
    Arc::new(Frame {
        pixels: RgbaImage::from_pixel(1, 1, Rgba([value, 0, 0, 255])),
        delay: Duration::from_millis(100),
    })
}

#[test]
fn pending_frames_do_not_advance_texture_serial_before_their_deadline() -> Result<()> {
    let (mut player, send, now) = scripted();
    send.send(Ok(frame(1)))?;
    send.send(Ok(frame(2)))?;
    assert!(player.tick(now));
    assert_eq!(player.frame_serial, 1);
    assert!(player.tick(now + Duration::from_millis(99)));
    assert_eq!(player.frame_serial, 1);
    assert!(player.tick(now + Duration::from_millis(100)));
    assert_eq!(player.frame_serial, 2);
    assert_eq!(
        player.current.as_ref().map(|f| f.pixels[(0, 0)][0]),
        Some(2)
    );
    Ok(())
}

#[test]
fn pause_retains_remaining_time_and_no_static_busy_presentations() -> Result<()> {
    let (mut player, send, now) = scripted();
    send.send(Ok(frame(1)))?;
    send.send(Ok(frame(2)))?;
    assert!(player.tick(now));
    player.toggle_pause(now + Duration::from_millis(40));
    assert!(player.tick(now + Duration::from_secs(5)));
    assert_eq!(player.frame_serial, 1);
    player.toggle_pause(now + Duration::from_millis(5040));
    assert!(player.tick(now + Duration::from_millis(5099)));
    assert_eq!(player.frame_serial, 1);
    assert!(player.tick(now + Duration::from_millis(5100)));
    assert_eq!(player.frame_serial, 2);
    Ok(())
}

#[test]
fn absolute_deadlines_catch_up_without_adding_swap_time_and_return_after_last_frame() -> Result<()>
{
    let (mut player, send, now) = scripted();
    send.send(Ok(frame(1)))?;
    send.send(Ok(frame(2)))?;
    assert!(player.tick(now));
    assert!(player.tick(now + Duration::from_millis(250)));
    assert_eq!(player.deadline, Some(now + Duration::from_millis(200)));
    assert_eq!(player.skipped, 1);
    drop(send);
    assert!(!player.tick(now + Duration::from_millis(250)));
    Ok(())
}

#[test]
fn preparing_gif_does_not_start_the_clock_or_count_a_failure() {
    let (mut player, _send, now) = scripted();
    player.decoder = None;
    player.preparing = true;
    assert!(player.tick(now));
    assert!(player.tick(now + Duration::from_secs(20)));
    assert!(player.deadline.is_none());
    assert!(player.current.is_none());
    assert_eq!(player.failures, 0);
}
