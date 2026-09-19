//! Pure Rust raster/GIF decoding; the same external `FFmpeg` `WebM` path as Python.
use crate::{model::Kind, process, storage};
use anyhow::{Context, Result, bail, ensure};
use image::{AnimationDecoder, ImageDecoder, ImageFormat, ImageReader, RgbaImage};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{BufReader, Read, Seek, SeekFrom, Write};
use std::os::fd::AsFd;
use std::process::{Command, Stdio};
use std::sync::atomic::AtomicBool;
use std::time::{Duration, Instant};

#[derive(Debug)]
pub struct Frame {
    pub pixels: RgbaImage,
    pub delay: Duration,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Info {
    pub kind: Kind,
}

fn dimensions(width: u32, height: u32, maximum: u64) -> Result<()> {
    ensure!(
        width > 0 && height > 0 && u64::from(width) * u64::from(height) <= maximum,
        "Media dimensions exceed limit"
    );
    Ok(())
}

fn rewind(file: &File) -> Result<BufReader<File>> {
    let mut reader = BufReader::new(file.try_clone()?);
    reader.seek(SeekFrom::Start(0))?;
    Ok(reader)
}

fn format(file: &File) -> Result<Kind> {
    let mut prefix = [0; 64];
    let count = rewind(file)?.read(&mut prefix)?;
    if prefix.starts_with(&[0x1a, 0x45, 0xdf, 0xa3]) {
        return Ok(Kind::Webm);
    }
    Ok(match image::guess_format(&prefix[..count])? {
        ImageFormat::Png => Kind::Png,
        ImageFormat::Jpeg => Kind::Jpeg,
        ImageFormat::WebP => Kind::Webp,
        ImageFormat::Gif => Kind::Gif,
        _ => bail!("Only PNG, JPEG, static WebP, GIF and WebM are accepted"),
    })
}

fn still(file: &File, kind: Kind) -> Result<RgbaImage> {
    match kind {
        Kind::Png => ensure!(
            !image::codecs::png::PngDecoder::new(rewind(file)?)?.is_apng()?,
            "Animated PNG is unsupported; use GIF/WebM"
        ),
        Kind::Webp => ensure!(
            !image::codecs::webp::WebPDecoder::new(rewind(file)?)?.has_animation(),
            "Animated WebP is unsupported; use GIF/WebM"
        ),
        _ => (),
    }
    let mut reader = ImageReader::new(rewind(file)?).with_guessed_format()?;
    let mut limits = image::Limits::default();
    limits.max_alloc = Some(128 * 1024 * 1024);
    reader.limits(limits);
    let mut decoder = reader.into_decoder()?;
    let (w, h) = decoder.dimensions();
    dimensions(w, h, 8_000_000)?;
    let orientation = decoder.orientation()?;
    let mut image = image::DynamicImage::from_decoder(decoder)?;
    image.apply_orientation(orientation);
    Ok(image.to_rgba8())
}

pub fn gif_delay(numerator: u32, denominator: u32) -> Duration {
    let millis = numerator.checked_div(denominator).unwrap_or(0);
    Duration::from_millis(u64::from(if millis == 0 {
        100
    } else {
        millis.clamp(20, 10_000)
    }))
}

fn gif(file: &File, emit: &mut impl FnMut(Frame) -> Result<()>) -> Result<()> {
    let mut decoder = image::codecs::gif::GifDecoder::new(rewind(file)?)?;
    let (w, h) = decoder.dimensions();
    dimensions(w, h, 1_000_000)?;
    let mut limits = image::Limits::default();
    limits.max_alloc = Some(64 * 1024 * 1024);
    decoder.set_limits(limits)?;
    let mut count = 0_u64;
    for frame in decoder.into_frames() {
        count += 1;
        ensure!(
            count <= 1000 && count * u64::from(w) * u64::from(h) <= 256_000_000,
            "GIF frame/aggregate limit exceeded"
        );
        let frame = frame?;
        let (n, d) = frame.delay().numer_denom_ms();
        emit(Frame {
            delay: gif_delay(n, d),
            pixels: frame.into_buffer(),
        })?;
    }
    ensure!(count > 0, "Empty GIF");
    Ok(())
}

fn ffmpeg_input(file: &File, executable: &str) -> Result<Command> {
    let mut input = file.try_clone()?;
    input.seek(SeekFrom::Start(0))?;
    let mut cmd = Command::new(executable);
    cmd.args([
        "-v",
        "error",
        "-threads",
        "1",
        "-protocol_whitelist",
        "file,pipe",
    ])
    .env("OMP_NUM_THREADS", "1")
    .env("OPENBLAS_NUM_THREADS", "1")
    .stdin(Stdio::from(input));
    Ok(cmd)
}

fn ebml_integer(bytes: &[u8], position: &mut usize, id: bool) -> Result<u64> {
    let first = *bytes.get(*position).context("Truncated EBML header")?;
    let length = usize::try_from(first.leading_zeros())? + 1;
    ensure!(length <= if id { 4 } else { 8 }, "Invalid EBML integer");
    let tail = bytes
        .get(*position + 1..*position + length)
        .context("Truncated EBML integer")?;
    let mut value = u64::from(if id {
        first
    } else {
        first & 0xff_u8.checked_shr(u32::try_from(length)?).unwrap_or(0)
    });
    for byte in tail {
        value = (value << 8) | u64::from(*byte);
    }
    *position += length;
    Ok(value)
}

fn webm_document(bytes: &[u8]) -> Result<()> {
    ensure!(
        bytes.starts_with(&[0x1a, 0x45, 0xdf, 0xa3]),
        "Expected EBML header"
    );
    let mut position = 4;
    let length = usize::try_from(ebml_integer(bytes, &mut position, false)?)?;
    let end = position.checked_add(length).context("EBML size overflow")?;
    ensure!(end <= bytes.len(), "Oversized EBML header");
    let header = &bytes[..end];
    let mut found = false;
    while position < end {
        let id = ebml_integer(header, &mut position, true)?;
        let length = usize::try_from(ebml_integer(header, &mut position, false)?)?;
        let next = position.checked_add(length).context("EBML size overflow")?;
        let value = header
            .get(position..next)
            .context("Truncated EBML element")?;
        if id == 0x4282 {
            ensure!(!found && value == b"webm", "Expected one WebM DocType");
            found = true;
        }
        position = next;
    }
    ensure!(found, "Missing WebM DocType");
    Ok(())
}

fn webm_probe(file: &File) -> Result<()> {
    let mut prefix = vec![0; 4096];
    let len = rewind(file)?.read(&mut prefix)?;
    prefix.truncate(len);
    webm_document(&prefix)?;
    let mut command = ffmpeg_input(file, "ffprobe")?;
    command.args(["-show_streams", "-show_format", "-of", "json", "pipe:0"]);
    let bytes = process::capture_in_group(
        &mut command,
        65536,
        Duration::from_secs(10),
        &AtomicBool::new(false),
    )?;
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    let stream = value["streams"]
        .as_array()
        .context("Missing WebM stream")?
        .iter()
        .find(|v| v["codec_type"] == "video")
        .context("No video stream")?;
    ensure!(
        matches!(stream["codec_name"].as_str(), Some("vp8" | "vp9" | "av1")),
        "Unsupported WebM codec"
    );
    let w = stream["width"].as_u64().context("Missing width")?;
    let h = stream["height"].as_u64().context("Missing height")?;
    ensure!(
        (1..=4096).contains(&w) && (1..=2160).contains(&h),
        "WebM dimensions exceed limit"
    );
    let duration = value["format"]["duration"]
        .as_str()
        .or_else(|| stream["duration"].as_str())
        .context("Unknown WebM duration")?
        .parse::<f64>()?;
    ensure!(
        duration.is_finite() && duration > 0.0 && duration <= 1800.0,
        "WebM duration exceeds limit"
    );
    Ok(())
}

fn webm(
    file: &File,
    size: (u32, u32),
    first: bool,
    emit: &mut impl FnMut(Frame) -> Result<()>,
) -> Result<()> {
    let (w, h) = (size.0.clamp(1, 1280), size.1.clamp(1, 720));
    let filter = format!(
        "scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,fps=20"
    );
    let mut cmd = ffmpeg_input(file, "ffmpeg")?;
    cmd.args([
        "-filter_threads",
        "1",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        &filter,
        "-pix_fmt",
        "rgba",
        "-f",
        "rawvideo",
    ]);
    if first {
        cmd.args(["-frames:v", "1"]);
    }
    cmd.arg("pipe:1");
    // Inherit the Rust decoder's group: cancelling it also terminates FFmpeg.
    let mut child = cmd.stdout(Stdio::piped()).stderr(Stdio::null()).spawn()?;
    let result = (|| -> Result<()> {
        let mut output = child.stdout.take().context("Missing FFmpeg output")?;
        let mut count = 0;
        loop {
            let mut buffer = vec![0; usize::try_from(w)? * usize::try_from(h)? * 4];
            match output.read_exact(&mut buffer) {
                Ok(()) => {
                    count += 1;
                    ensure!(count <= 36_001, "WebM frame limit exceeded");
                    emit(Frame {
                        pixels: RgbaImage::from_raw(w, h, buffer).context("Invalid video frame")?,
                        delay: Duration::from_millis(50),
                    })?;
                }
                Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => break,
                Err(e) => return Err(e.into()),
            }
        }
        ensure!(count > 0 && child.wait()?.success(), "WebM decode failed");
        Ok(())
    })();
    if result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

pub fn inspect(file: &File) -> Result<Info> {
    let kind = format(file)?;
    match kind {
        Kind::Gif => gif(file, &mut |_| Ok(()))?,
        Kind::Webm => {
            webm_probe(file)?;
            webm(file, (16, 16), true, &mut |_| Ok(()))?;
        }
        _ => {
            still(file, kind)?;
        }
    }
    Ok(Info { kind })
}

pub fn child(arguments: &[String]) -> Result<()> {
    let mode = arguments.first().context("Missing decoder mode")?;
    #[cfg(target_os = "linux")]
    process::limits(mode != "--decode")?;
    let file = File::from(std::io::stdin().as_fd().try_clone_to_owned()?);
    ensure!(
        (1..=storage::MAX_UPLOAD).contains(&file.metadata()?.len()),
        "Media size exceeds limit"
    );
    if mode == "--inspect" {
        serde_json::to_writer(std::io::stdout(), &inspect(&file)?)?;
        return Ok(());
    }
    let w = arguments.get(1).context("Missing width")?.parse::<u32>()?;
    let h = arguments.get(2).context("Missing height")?.parse::<u32>()?;
    let repeats = arguments
        .get(3)
        .context("Missing repeats")?
        .parse::<u32>()?;
    ensure!(
        (1..=100).contains(&repeats) && w <= 1280 && h <= 720 && w > 0 && h > 0,
        "Invalid decode parameters"
    );
    let kind = format(&file)?;
    if let Some(expected) = arguments.get(4) {
        ensure!(
            serde_json::from_str::<Kind>(expected)? == kind,
            "Media type no longer matches the library"
        );
    }
    let mut output = std::io::stdout().lock();
    let mut emit = |frame: &Frame| -> Result<()> {
        if mode == "--thumbnail" {
            let small = Frame {
                pixels: image::imageops::thumbnail(&frame.pixels, w, h),
                delay: frame.delay,
            };
            write_frame(&mut output, &small)
        } else {
            write_frame(&mut output, frame)
        }
    };
    match kind {
        Kind::Gif => {
            // Cache only small composited animations; larger ones stream through
            // two parent-side slots and are decoded again for each complete play.
            let mut cache = Vec::new();
            let mut bytes = 0;
            gif(&file, &mut |frame| {
                emit(&frame)?;
                bytes += frame.pixels.len();
                if bytes <= 8 * 1024 * 1024 {
                    cache.push(frame);
                } else {
                    cache.clear();
                }
                Ok(())
            })?;
            for _ in 1..repeats {
                if cache.is_empty() {
                    gif(&file, &mut |frame| emit(&frame))?;
                } else {
                    for frame in &cache {
                        emit(frame)?;
                    }
                }
            }
        }
        Kind::Webm => {
            webm_probe(&file)?;
            for _ in 0..repeats {
                webm(&file, (w, h), mode == "--thumbnail", &mut |frame| {
                    emit(&frame)
                })?;
            }
        }
        _ => emit(&Frame {
            pixels: still(&file, kind)?,
            delay: Duration::ZERO,
        })?,
    }
    Ok(())
}

fn write_frame(output: &mut impl Write, frame: &Frame) -> Result<()> {
    for value in [
        frame.pixels.width(),
        frame.pixels.height(),
        u32::try_from(frame.delay.as_millis())?,
        u32::try_from(frame.pixels.len())?,
    ] {
        output.write_all(&value.to_le_bytes())?;
    }
    output.write_all(&frame.pixels)?;
    output.flush()?;
    Ok(())
}

pub fn command(file: File, mode: &str, size: (u32, u32), repeats: u32) -> Result<Command> {
    #[cfg(not(test))]
    let executable = std::env::current_exe()?;
    #[cfg(test)]
    let executable = std::env::var_os("CAROUSEL_RUST_TEST_BINARY")
        .map_or_else(std::env::current_exe, |s| Ok(std::path::PathBuf::from(s)))?;
    let mut command = Command::new(executable);
    command
        .args([
            mode,
            &size.0.to_string(),
            &size.1.to_string(),
            &repeats.to_string(),
        ])
        .stdin(file);
    Ok(command)
}

pub fn isolated_inspect(file: File, cancel: &AtomicBool) -> Result<Info> {
    let bytes = process::capture(
        &mut command(file, "--inspect", (16, 16), 1)?,
        4096,
        Duration::from_secs(35),
        cancel,
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

pub fn read_frame<R: Read + std::os::fd::AsRawFd>(
    output: &mut R,
    cancel: &AtomicBool,
    deadline: Instant,
) -> Result<Option<Frame>> {
    let mut header = [0; 16];
    if !process::read_exact(output, &mut header, cancel, deadline)? {
        return Ok(None);
    }
    let mut values = [0; 4];
    for (value, chunk) in values.iter_mut().zip(header.as_chunks::<4>().0) {
        *value = u32::from_le_bytes(*chunk);
    }
    let [w, h, delay, count] = values;
    dimensions(w, h, 8_000_000)?;
    ensure!(
        u64::from(count) == u64::from(w) * u64::from(h) * 4 && delay <= 10_000,
        "Invalid decoder frame header"
    );
    let mut bytes = vec![0; usize::try_from(count)?];
    ensure!(
        process::read_exact(output, &mut bytes, cancel, deadline)?,
        "Missing frame pixels"
    );
    Ok(Some(Frame {
        pixels: RgbaImage::from_raw(w, h, bytes).context("Invalid RGBA")?,
        delay: Duration::from_millis(u64::from(delay)),
    }))
}
