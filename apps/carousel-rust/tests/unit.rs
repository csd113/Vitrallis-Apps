//! Behavioral regression tests; excluded from installed packages.
use crate::{
    http, media,
    model::{self, Collection, Item, Kind, Library, Order, Settings, Store},
    player, render, server, storage,
    ui::{Screen, Ui},
};
use anyhow::Result;
use sdl2::keyboard::Keycode;
use std::fs;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt, symlink};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

struct Fixture(std::path::PathBuf);
impl Fixture {
    fn new() -> Result<Self> {
        let base = std::env::temp_dir()
            .canonicalize()?
            .join(format!("carousel-test-{}", storage::random_id()));
        fs::DirBuilder::new().mode(0o700).create(&base)?;
        Ok(Self(base))
    }
    fn paths(&self) -> Result<storage::Paths> {
        storage::Paths::create(
            self.0.join("config"),
            self.0.join("data"),
            &self.0.join("cache"),
            &self.0.join("package"),
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn item(n: u8) -> Item {
    Item {
        id: format!("{n:032x}"),
        name: format!("Image {n}.png"),
        kind: Kind::Png,
        size: 123,
    }
}

#[test]
fn metadata_matches_python_and_rejects_ambiguous_restores() -> Result<()> {
    let raw = br#"{"version":1,"collections":[{"id":"00000000000000000000000000000001","name":"Unsorted","items":[]}]}"#;
    let library: Library = serde_json::from_slice(raw)?;
    library.validate()?;
    for invalid in [
        br#"{"version":1,"version":1,"collections":[]}"#.as_slice(),
        br#"{"version":true,"collections":[]}"#,
        br#"{"version":1,"collections":[],"extra":0}"#,
    ] {
        assert!(serde_json::from_slice::<Library>(invalid).is_err());
    }
    let mut duplicate = library;
    let mut row = Collection::new("UNSORTED".into());
    row.items.push(item(1));
    duplicate.collections.push(row);
    assert!(duplicate.validate().is_err());
    assert!(model::identifier("../../etc/passwd").is_err());
    assert_eq!(model::name(" e\u{301} ", 64)?, "é");
    for bad in ["../photo", "a/b", "a\\b", "x:y", "a\0b", "a\u{200b}b"] {
        assert!(model::name(bad, 160).is_err());
    }
    Ok(())
}

#[test]
fn settings_exact_types_limits_and_serialization() -> Result<()> {
    assert_eq!(
        serde_json::to_value(Settings::default())?,
        serde_json::json!({"image_seconds":5,"repeats":3,"order":"ordered","loop":true})
    );
    for seconds in [0, 3601] {
        assert!(
            Settings {
                image_seconds: seconds,
                ..Settings::default()
            }
            .validate()
            .is_err()
        );
    }
    for count in [0, 101] {
        assert!(
            Settings {
                repeats: count,
                ..Settings::default()
            }
            .validate()
            .is_err()
        );
    }
    assert!(
        serde_json::from_str::<Settings>(
            r#"{"image_seconds":true,"repeats":3,"order":"ordered","loop":true}"#
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn shared_flock_blocks_python_and_second_rust_writer() -> Result<()> {
    let fixture = Fixture::new()?;
    let paths = fixture.paths()?;
    let store = Store::open(paths.clone())?;
    assert!(Store::open(paths.clone()).is_err());
    let status = std::process::Command::new("python3").args(["-c", "import fcntl,sys; f=open(sys.argv[1],'r+'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"]).arg(paths.data.join("instance.lock")).stderr(std::process::Stdio::null()).status()?;
    assert!(!status.success());
    drop(store);
    Store::open(paths)?;
    Ok(())
}

#[test]
fn unsafe_roots_and_files_fail_before_mutation() -> Result<()> {
    let fixture = Fixture::new()?;
    let link = fixture.0.join("link");
    symlink(&fixture.0, &link)?;
    assert!(
        storage::Paths::create(
            fixture.0.join("new-config"),
            link.join("data"),
            &fixture.0.join("cache"),
            &fixture.0.join("package")
        )
        .is_err()
    );
    assert!(!fixture.0.join("new-config").exists());
    let paths = fixture.paths()?;
    let original = paths.data.join("original");
    fs::write(&original, b"private")?;
    let other = paths.data.join("other");
    fs::hard_link(&original, &other)?;
    assert!(storage::regular(&original, 100).is_err());
    fs::remove_file(&other)?;
    symlink(&original, &other)?;
    assert!(storage::regular(&other, 100).is_err());
    assert!(storage::regular(&original, 1).is_err());
    fs::set_permissions(&paths.data, fs::Permissions::from_mode(0o755))?;
    assert!(storage::regular(&original, 100).is_err());
    Ok(())
}

#[test]
fn atomic_failure_preserves_metadata_and_corruption_is_not_replaced() -> Result<()> {
    let fixture = Fixture::new()?;
    let paths = fixture.paths()?;
    let path = paths.data.join("library.json");
    let store = Store::open(paths.clone())?;
    drop(store);
    let before = fs::read(&path)?;
    assert!(storage::atomic_json(&path, &vec![0; 100], 10).is_err());
    assert_eq!(fs::read(&path)?, before);
    fs::write(&path, b"corrupt")?;
    assert!(Store::open(paths).is_err());
    assert_eq!(fs::read(path)?, b"corrupt");
    Ok(())
}

#[test]
fn uploads_and_deletion_round_trip_shared_python_schema() -> Result<()> {
    let fixture = Fixture::new()?;
    let mut store = Store::open(fixture.paths()?)?;
    let cid = store.library.collections[0].id.clone();
    let mut temp = storage::Temporary::new(&store.paths.uploads, "upload-")?;
    temp.file.write_all(b"fixture bytes")?;
    temp.file.sync_all()?;
    let added = store.upload(&cid, "Image.png", &temp, Kind::Png)?;
    assert_eq!(
        storage::read(&store.paths.media.join(&added.id), 100)?,
        b"fixture bytes"
    );
    let paths = store.paths.clone();
    drop(store);
    let mut restored = Store::open(paths)?;
    assert_eq!(restored.library.row(&cid)?.items[0].id, added.id);
    restored.delete(&cid, Some(&added.id))?;
    assert!(!restored.paths.media.join(&added.id).exists());
    restored.delete(&cid, None)?;
    assert_eq!(restored.library.collections[0].name, "Unsorted");
    Ok(())
}

#[test]
fn image_formats_are_sniffed_from_bytes_and_gif_timing_is_clamped() -> Result<()> {
    let fixture = Fixture::new()?;
    for format in [
        image::ImageFormat::Png,
        image::ImageFormat::Jpeg,
        image::ImageFormat::WebP,
        image::ImageFormat::Gif,
    ] {
        let mut file = fs::File::create(fixture.0.join("image"))?;
        image::RgbImage::from_pixel(3, 2, image::Rgb([23, 45, 67])).write_to(&mut file, format)?;
        let info = media::inspect(&fs::File::open(fixture.0.join("image"))?)?;
        assert_eq!(
            info.kind,
            match format {
                image::ImageFormat::Png => Kind::Png,
                image::ImageFormat::Jpeg => Kind::Jpeg,
                image::ImageFormat::WebP => Kind::Webp,
                _ => Kind::Gif,
            }
        );
    }
    assert_eq!(media::gif_delay(0, 1), Duration::from_millis(100));
    assert_eq!(media::gif_delay(1, 1), Duration::from_millis(20));
    assert_eq!(media::gif_delay(20_000, 1), Duration::from_secs(10));
    Ok(())
}

#[test]
fn http_rejects_smuggling_rebinding_cross_origin_and_filename_traversal() -> Result<()> {
    let parse = |text: &str| http::Request::from_header(text.as_bytes(), 8765, Instant::now());
    assert!(parse("GET /api/state HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n\r\n").is_ok());
    for headers in [
        "Host: localhost:8765",
        "Host: evil.test:8765",
        "Host: 127.0.0.1:80",
        "Host: 127.0.0.1:8765\r\nHost: 127.0.0.1:8765",
        "Host: 127.0.0.1:8765\r\nOrigin: http://evil.test",
        "Host: 127.0.0.1:8765\r\nTransfer-Encoding: chunked",
        "Host: 127.0.0.1:8765\r\nContent-Length: 1\r\nContent-Length: 2",
    ] {
        assert!(parse(&format!("GET /api/state HTTP/1.1\r\n{headers}\r\n\r\n")).is_err());
    }
    for query in [
        "name=..%2Fsecret",
        "name=a%00.png",
        "name=ok.png&x=1",
        "name=%zz",
    ] {
        assert!(http::filename(query).is_err());
    }
    assert_eq!(http::filename("name=caf%C3%A9.png")?, "café.png");
    Ok(())
}

fn request(
    service: &server::Service,
    method: &str,
    path: &str,
    body: Option<&str>,
    authenticated: bool,
) -> Result<(u16, serde_json::Value)> {
    let mut stream = TcpStream::connect(("127.0.0.1", service.port))?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    let auth = if authenticated {
        format!("Authorization: Bearer {}\r\n", service.token)
    } else {
        String::new()
    };
    let payload = body.unwrap_or("");
    write!(
        stream,
        "{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:{}\r\n{auth}Content-Type: application/json\r\nContent-Length: {}\r\n\r\n{payload}",
        service.port,
        payload.len()
    )?;
    let mut response = String::new();
    stream.read_to_string(&mut response)?;
    let (head, body) = response
        .split_once("\r\n\r\n")
        .ok_or_else(|| anyhow::anyhow!("Missing response"))?;
    let status = head
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("Missing status"))?
        .parse()?;
    Ok((status, serde_json::from_str(body)?))
}

#[test]
fn keyboard_baseline_and_authenticated_management_round_trip() -> Result<()> {
    let fixture = Fixture::new()?;
    let shared = Arc::new(Mutex::new(Store::open(fixture.paths()?)?));
    let server = server::Server::start(
        Arc::clone(&shared),
        crate::process::stopped(),
        "127.0.0.1",
        0,
    )?;
    let service = &server.service;
    assert_eq!(request(service, "GET", "/api/state", None, false)?.0, 401);
    let (status, row) = request(
        service,
        "POST",
        "/api/collections",
        Some(r#"{"name":"Holiday"}"#),
        true,
    )?;
    assert_eq!(status, 201);
    let cid = row["id"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("Missing ID"))?;
    assert_eq!(
        request(
            service,
            "PUT",
            &format!("/api/collections/{cid}"),
            Some(r#"{"name":"Trip"}"#),
            true
        )?
        .0,
        200
    );
    assert_eq!(
        request(service, "GET", "/api/state", None, true)?.1["collections"][1]["name"],
        "Trip"
    );
    let mut ui = Ui::new(Settings::default());
    ui.key(Keycode::F1, false, service)?;
    assert_eq!(ui.screen, Screen::Help);
    ui.key(Keycode::Escape, false, service)?;
    ui.key(Keycode::Down, false, service)?;
    assert_eq!(ui.selected, 1);
    ui.key(Keycode::S, false, service)?;
    ui.key(Keycode::Right, false, service)?;
    assert_eq!(ui.edit.image_seconds, 6);
    ui.key(Keycode::Escape, false, service)?;
    assert_eq!(server::lock(&shared)?.settings.image_seconds, 5);
    ui.key(Keycode::S, false, service)?;
    ui.key(Keycode::Right, false, service)?;
    for _ in 0..4 {
        ui.key(Keycode::Tab, false, service)?;
    }
    ui.key(Keycode::Return, false, service)?;
    assert_eq!(server::lock(&shared)?.settings.image_seconds, 6);
    ui.focus = 0;
    ui.key(Keycode::Return, false, service)?;
    assert_eq!(ui.screen, Screen::Playback);
    ui.key(Keycode::Space, false, service)?;
    assert!(ui.player.as_ref().is_some_and(|p| p.paused));
    if let Some(player) = &mut ui.player {
        player.decoded = 7;
        player.skipped = 2;
    }
    ui.key(Keycode::Escape, false, service)?;
    assert!(ui.player.is_none());
    assert_eq!(ui.metrics(), (7, 2));
    ui.key(Keycode::Escape, false, service)?;
    assert!(ui.quit);
    assert_eq!(
        request(
            service,
            "DELETE",
            &format!("/api/collections/{cid}"),
            None,
            true
        )?
        .0,
        200
    );
    Ok(())
}

#[test]
fn shuffle_visits_every_item_without_boundary_repeat_and_fit_letterboxes() -> Result<()> {
    let mut items = vec![item(1), item(2), item(3)];
    for _ in 0..100 {
        player::shuffle(&mut items, Some(&format!("{:032x}", 1)));
        assert_ne!(items[0].id, format!("{:032x}", 1));
        let unique: std::collections::HashSet<_> = items.iter().map(|i| &i.id).collect();
        assert_eq!(unique.len(), 3);
    }
    assert_eq!(
        render::fit((100, 100), (480, 272))?,
        sdl2::rect::Rect::new(104, 0, 272, 272)
    );
    assert_eq!(Settings::default().order, Order::Ordered);
    Ok(())
}

fn raw_request(
    service: &server::Service,
    method: &str,
    path: &str,
    mime: &str,
    body: &[u8],
) -> Result<(u16, Vec<u8>)> {
    let mut stream = TcpStream::connect(("127.0.0.1", service.port))?;
    stream.set_read_timeout(Some(Duration::from_secs(40)))?;
    write!(
        stream,
        "{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:{}\r\nAuthorization: Bearer {}\r\nContent-Type: {mime}\r\nContent-Length: {}\r\n\r\n",
        service.port,
        service.token,
        body.len()
    )?;
    stream.write_all(body)?;
    let mut response = Vec::new();
    stream.read_to_end(&mut response)?;
    let split = response
        .windows(4)
        .position(|s| s == b"\r\n\r\n")
        .ok_or_else(|| anyhow::anyhow!("Missing response"))?;
    let head = std::str::from_utf8(&response[..split])?;
    let code = head
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("Missing status"))?
        .parse()?;
    assert!(head.contains("X-Content-Type-Options: nosniff"));
    Ok((code, response[split + 4..].to_vec()))
}

#[test]
#[ignore = "requires CAROUSEL_RUST_TEST_BINARY pointing at a freshly built host executable"]
fn real_http_upload_validation_thumbnail_archive_and_shutdown() -> Result<()> {
    anyhow::ensure!(
        std::env::var_os("CAROUSEL_RUST_TEST_BINARY").is_some(),
        "Provide host executable"
    );
    let fixture = Fixture::new()?;
    let paths = fixture.paths()?;
    let shared = Arc::new(Mutex::new(Store::open(paths.clone())?));
    let server = server::Server::start(
        Arc::clone(&shared),
        crate::process::stopped(),
        "127.0.0.1",
        0,
    )?;
    let service = &server.service;
    let cid = server::lock(&shared)?.library.collections[0].id.clone();
    let mut png = std::io::Cursor::new(Vec::new());
    image::RgbaImage::from_pixel(320, 160, image::Rgba([180, 40, 20, 128]))
        .write_to(&mut png, image::ImageFormat::Png)?;
    let (status, bytes) = raw_request(
        service,
        "POST",
        &format!("/api/collections/{cid}/media?name=photo.jpg"),
        "application/octet-stream",
        png.get_ref(),
    )?;
    assert_eq!(status, 201, "{}", String::from_utf8_lossy(&bytes));
    let item: Item = serde_json::from_slice(&bytes)?;
    assert_eq!(item.kind, Kind::Png);
    assert_eq!(fs::read(paths.media.join(&item.id))?, *png.get_ref());
    let (status, bytes) = raw_request(
        service,
        "GET",
        &format!("/api/collections/{cid}/media/{}/thumbnail", item.id),
        "application/json",
        &[],
    )?;
    assert_eq!(status, 200, "{}", String::from_utf8_lossy(&bytes));
    let preview = image::load_from_memory(&bytes)?;
    assert!(preview.width() <= 128 && preview.height() <= 80);
    let (status, bytes) = raw_request(
        service,
        "GET",
        &format!("/api/collections/{cid}/download"),
        "application/json",
        &[],
    )?;
    assert_eq!(status, 200);
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(bytes))?;
    let mut saved = Vec::new();
    archive.by_index(0)?.read_to_end(&mut saved)?;
    assert_eq!(saved, *png.get_ref());
    let (status, _) = raw_request(
        service,
        "POST",
        &format!("/api/collections/{cid}/media?name=bad.png"),
        "application/octet-stream",
        b"invalid media",
    )?;
    assert_eq!(status, 400);
    assert_eq!(server::lock(&shared)?.library.row(&cid)?.items.len(), 1);
    let mut slow = TcpStream::connect(("127.0.0.1", service.port))?;
    write!(
        slow,
        "POST /api/collections/{cid}/media?name=incomplete.png HTTP/1.0\r\nHost: 127.0.0.1:{}\r\nAuthorization: Bearer {}\r\nContent-Type: application/octet-stream\r\nContent-Length: 10000\r\n\r\npartial",
        service.port, service.token
    )?;
    std::thread::sleep(Duration::from_millis(100));
    let before = Instant::now();
    drop(server);
    assert!(before.elapsed() < Duration::from_secs(4));
    assert_eq!(fs::read_dir(&paths.uploads)?.count(), 0);
    Ok(())
}

#[test]
fn publication_collision_does_not_replace_a_blob_or_leave_hardlinks() -> Result<()> {
    let fixture = Fixture::new()?;
    let paths = fixture.paths()?;
    let source = paths.uploads.join("upload-test");
    let destination = paths.media.join("reserved");
    fs::write(&source, b"incoming")?;
    fs::write(&destination, b"existing")?;
    assert!(storage::publish(&source, &destination).is_err());
    assert_eq!(fs::read(&source)?, b"incoming");
    assert_eq!(fs::read(&destination)?, b"existing");
    fs::remove_file(&destination)?;
    storage::publish(&source, &destination)?;
    assert!(!source.exists());
    assert_eq!(storage::read(&destination, 100)?, b"incoming");
    Ok(())
}

#[test]
fn binding_failure_keeps_native_navigation_available() -> Result<()> {
    let fixture = Fixture::new()?;
    let shared = Arc::new(Mutex::new(Store::open(fixture.paths()?)?));
    let server = server::Server::start(
        Arc::clone(&shared),
        crate::process::stopped(),
        "192.0.2.1",
        8765,
    )?;
    assert_eq!(server.service.port, 0);
    assert!(
        server::lock(&shared)?
            .warning
            .contains("LAN management unavailable")
    );
    let mut ui = Ui::new(Settings::default());
    ui.key(Keycode::S, false, &server.service)?;
    assert_eq!(ui.screen, Screen::Settings);
    Ok(())
}
