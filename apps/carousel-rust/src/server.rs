//! LAN management API. The browser assets and routes match the Python carousel.
use crate::{
    http::{self, Request},
    media,
    model::{self, Collection, Store},
    process, storage,
};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::json;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::{
    Arc, Mutex, MutexGuard,
    atomic::{AtomicBool, Ordering},
};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

pub type Shared = Arc<Mutex<Store>>;

pub fn lock(store: &Shared) -> Result<MutexGuard<'_, Store>> {
    store
        .lock()
        .map_err(|_| anyhow::anyhow!("Storage lock poisoned"))
}

pub struct Service {
    pub store: Shared,
    pub token: String,
    pub port: u16,
    pub stop: Arc<AtomicBool>,
    pub urls: Mutex<Vec<String>>,
    pub capabilities: Mutex<serde_json::Value>,
    pub installation: Mutex<serde_json::Value>,
    pub media_slot: Mutex<()>,
    uploads: Mutex<usize>,
    auth: Mutex<(Instant, u32)>,
    download: Mutex<()>,
    previews: Mutex<std::collections::VecDeque<(String, Vec<u8>)>>,
}

pub struct Server {
    pub service: Arc<Service>,
    thread: Option<JoinHandle<()>>,
}

impl Server {
    pub fn start(store: Shared, stop: Arc<AtomicBool>, bind: &str, port: u16) -> Result<Self> {
        let listener = TcpListener::bind((bind, port))
            .or_else(|e| {
                if port == 8765 && e.kind() == std::io::ErrorKind::AddrInUse {
                    TcpListener::bind((bind, 0))
                } else {
                    Err(e)
                }
            })
            .and_then(|listener| {
                listener.set_nonblocking(true)?;
                Ok(listener)
            });
        let listener = match listener {
            Ok(listener) => Some(listener),
            Err(error) => {
                lock(&store)?.warning = format!("LAN management unavailable: {error}");
                None
            }
        };
        let port = listener
            .as_ref()
            .map(TcpListener::local_addr)
            .transpose()?
            .map_or(0, |a| a.port());
        let service = Arc::new(Service {
            store,
            token: format!("{:06x}", rand::random::<u32>() & 0xff_ffff),
            port,
            stop,
            urls: Mutex::new(Vec::new()),
            capabilities: Mutex::new(
                json!({"ready": false, "webm": false, "webm_note": "Checking decoders…"}),
            ),
            installation: Mutex::new(
                json!({"status":"idle", "available":false, "message":"Checking multimedia support…"}),
            ),
            media_slot: Mutex::new(()),
            uploads: Mutex::new(0),
            auth: Mutex::new((Instant::now(), 0)),
            download: Mutex::new(()),
            previews: Mutex::new(std::collections::VecDeque::new()),
        });
        let owner = Arc::clone(&service);
        let thread = listener.map(|listener| std::thread::spawn(move || serve(&owner, &listener)));
        Ok(Self { service, thread })
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.service.stop.store(true, Ordering::Relaxed);
        // The explicitly authorized no-argument installer may be running dpkg.
        // Keep the application alive until it finishes; never kill its transaction.
        while self
            .service
            .installation
            .lock()
            .is_ok_and(|s| s["status"] == "running")
        {
            std::thread::sleep(Duration::from_millis(100));
        }
        if let Some(thread) = self.thread.take()
            && thread.join().is_err()
        {
            eprintln!("event=http_join_failed");
        }
    }
}

fn serve(owner: &Arc<Service>, listener: &TcpListener) {
    let probes = Arc::clone(owner);
    let probe = std::thread::spawn(move || crate::support::refresh(&probes));
    let mut workers: Vec<(JoinHandle<()>, TcpStream, Instant)> = Vec::new();
    let mut refresh = Instant::now()
        .checked_sub(Duration::from_secs(10))
        .unwrap_or_else(Instant::now);
    while !owner.stop.load(Ordering::Relaxed) {
        workers.retain(|(thread, _, _)| !thread.is_finished());
        for (_, socket, started) in &workers {
            if started.elapsed() > Duration::from_secs(160) {
                let _ = socket.shutdown(Shutdown::Both);
            }
        }
        if refresh.elapsed() >= Duration::from_secs(10) {
            if let Ok(mut urls) = owner.urls.lock() {
                *urls = crate::support::urls(owner.port);
            }
            refresh = Instant::now();
        }
        match listener.accept() {
            Ok((mut stream, address))
                if workers.len() < 4
                    && matches!(address.ip(), std::net::IpAddr::V4(ip) if http::private(ip)) =>
            {
                let Ok(socket) = stream.try_clone() else {
                    continue;
                };
                let service = Arc::clone(owner);
                let thread = std::thread::spawn(move || {
                    if let Err(e) = handle(&service, &mut stream) {
                        let _ = http::json(
                            &mut stream,
                            400,
                            &json!({"error":e.to_string().chars().take(200).collect::<String>()}),
                        );
                    }
                    let _ = stream.shutdown(Shutdown::Both);
                });
                workers.push((thread, socket, Instant::now()));
            }
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(e) => {
                eprintln!("event=http_accept_failed error={e}");
                break;
            }
        }
    }
    for (_, socket, _) in &workers {
        let _ = socket.shutdown(Shutdown::Both);
    }
    for (thread, _, _) in workers {
        let _ = thread.join();
    }
    let _ = probe.join();
}

impl Service {
    pub fn authenticated(&self, value: Option<&String>) -> Result<bool> {
        let expected = format!("Bearer {}", self.token);
        let supplied = value.map_or(&[][..], |s| s.as_bytes());
        let diff = supplied
            .iter()
            .zip(expected.bytes())
            .fold(0_u8, |acc, (a, b)| acc | (a ^ b));
        if supplied.len() == expected.len() && diff == 0 {
            return Ok(true);
        }
        let mut state = self
            .auth
            .lock()
            .map_err(|_| anyhow::anyhow!("Authentication unavailable"))?;
        if state.0.elapsed() >= Duration::from_secs(60) {
            *state = (Instant::now(), 0);
        }
        state.1 = state.1.saturating_add(1);
        ensure!(state.1 <= 30, "Too many invalid codes; wait a minute");
        drop(state);
        Ok(false)
    }
}

fn handle(owner: &Arc<Service>, stream: &mut TcpStream) -> Result<()> {
    let request = Request::parse(stream, owner.port, &owner.stop)?;
    if request.method == "GET" && request.query.is_empty() {
        let asset = match request.path.as_str() {
            "/" => Some((
                "text/html; charset=utf-8",
                include_bytes!("../web/index.html").as_slice(),
            )),
            "/app.js" => Some((
                "text/javascript; charset=utf-8",
                include_bytes!("../web/app.js").as_slice(),
            )),
            "/style.css" => Some((
                "text/css; charset=utf-8",
                include_bytes!("../web/style.css").as_slice(),
            )),
            _ => None,
        };
        if let Some((mime, bytes)) = asset {
            return http::reply(stream, 200, mime, bytes);
        }
    }
    match owner.authenticated(request.headers.get("authorization")) {
        Ok(true) => (),
        Ok(false) => {
            return http::json(
                stream,
                401,
                &json!({"error":"Enter the code displayed on the device"}),
            );
        }
        Err(_) => {
            return http::json(
                stream,
                429,
                &json!({"error":"Too many invalid codes; wait a minute"}),
            );
        }
    }
    let parts: Vec<_> = request.path.trim_start_matches('/').split('/').collect();
    match (request.method.as_str(), parts.as_slice()) {
        ("GET", ["api", "state"]) => state(owner, stream),
        ("PUT", ["api", "settings"]) => {
            let settings = request.json(stream, &owner.stop)?;
            let mut store = lock(&owner.store)?;
            store.save_settings(settings)?;
            let value = store.settings.clone();
            drop(store);
            http::json(stream, 200, &value)
        }
        ("POST", ["api", "dependencies", "install"]) => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Install {
                install: String,
            }
            let body: Install = request.json(stream, &owner.stop)?;
            ensure!(
                body.install == "ffmpeg",
                "Expected explicit FFmpeg installation request"
            );
            http::json(stream, 202, &crate::support::install(owner)?)
        }
        ("POST", ["api", "collections"]) => {
            let body: Name = request.json(stream, &owner.stop)?;
            let row = Collection::new(model::name(&body.name, 64)?);
            let mut store = lock(&owner.store)?;
            let mut next = store.library.clone();
            next.collections.push(row.clone());
            store.commit(next)?;
            drop(store);
            http::json(stream, 201, &row)
        }
        (method, ["api", "collections", cid, rest @ ..]) => {
            collection(owner, stream, &request, method, cid, rest)
        }
        _ => http::json(stream, 404, &json!({"error":"Unknown route"})),
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Name {
    name: String,
}

fn state(owner: &Service, stream: &mut TcpStream) -> Result<()> {
    // Clone bounded metadata, then release storage before network I/O.
    let value = {
        let store = lock(&owner.store)?;
        let value = json!({"collections":store.library.collections,"settings":store.settings,"warning":store.warning,
            "device":"Carousel-Rust", "urls":*owner.urls.lock().map_err(|_| anyhow::anyhow!("URLs unavailable"))?,
            "status":"Ready", "capabilities":*owner.capabilities.lock().map_err(|_| anyhow::anyhow!("Probes unavailable"))?,
            "installation":*owner.installation.lock().map_err(|_| anyhow::anyhow!("Installer unavailable"))?, "max_upload":storage::MAX_UPLOAD});
        drop(store);
        value
    };
    http::json(stream, 200, &value)
}

fn collection(
    owner: &Service,
    stream: &mut TcpStream,
    request: &Request,
    method: &str,
    cid: &str,
    rest: &[&str],
) -> Result<()> {
    model::identifier(cid)?;
    match (method, rest) {
        ("PUT", []) => {
            let body: Name = request.json(stream, &owner.stop)?;
            let mut store = lock(&owner.store)?;
            let mut next = store.library.clone();
            next.row_mut(cid)?.name = model::name(&body.name, 64)?;
            store.commit(next)?;
        }
        ("DELETE", []) => lock(&owner.store)?.delete(cid, None)?,
        ("DELETE", ["media", mid]) => lock(&owner.store)?.delete(cid, Some(mid))?,
        ("PUT", ["order"]) => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Order {
                ids: Vec<String>,
            }
            let body: Order = request.json(stream, &owner.stop)?;
            let mut store = lock(&owner.store)?;
            let mut next = store.library.clone();
            let row = next.row_mut(cid)?;
            ensure!(
                body.ids.len() == row.items.len(),
                "Ordering changed; refresh"
            );
            let mut items: std::collections::HashMap<_, _> =
                row.items.drain(..).map(|i| (i.id.clone(), i)).collect();
            for id in body.ids {
                row.items.push(
                    items
                        .remove(&id)
                        .context("Include each media ID exactly once")?,
                );
            }
            store.commit(next)?;
        }
        ("POST", ["media"]) => return upload(owner, stream, request, cid),
        ("GET", ["media", mid, "thumbnail"]) => return thumbnail(owner, stream, cid, mid),
        ("GET", ["download"]) => return download(owner, stream, cid),
        _ => return http::json(stream, 404, &json!({"error":"Unknown route"})),
    }
    http::json(stream, 200, &json!({"ok":true}))
}

struct UploadSlot<'a>(&'a Mutex<usize>);
impl Drop for UploadSlot<'_> {
    fn drop(&mut self) {
        if let Ok(mut count) = self.0.lock() {
            *count = count.saturating_sub(1);
        }
    }
}

fn upload(owner: &Service, stream: &mut TcpStream, request: &Request, cid: &str) -> Result<()> {
    let filename = http::filename(&request.query)?;
    request.length(storage::MAX_UPLOAD)?;
    ensure!(
        request
            .headers
            .get("content-type")
            .is_some_and(|s| s == "application/octet-stream"),
        "Expected binary upload"
    );
    {
        let mut count = owner
            .uploads
            .lock()
            .map_err(|_| anyhow::anyhow!("Uploads unavailable"))?;
        ensure!(*count < 2, "Two uploads are already active");
        *count += 1;
    }
    let _slot = UploadSlot(&owner.uploads);
    let mut temp = {
        let store = lock(&owner.store)?;
        store.library.row(cid)?;
        storage::Temporary::new(&store.paths.uploads, "upload-")?
    };
    request.copy_body(stream, &mut temp.file, storage::MAX_UPLOAD, &owner.stop)?;
    temp.file.sync_all()?;
    let _decoder = owner
        .media_slot
        .lock()
        .map_err(|_| anyhow::anyhow!("Decoder unavailable"))?;
    let info = media::isolated_inspect(
        storage::regular(&temp.path, storage::MAX_UPLOAD)?,
        &owner.stop,
    )?;
    ensure!(!owner.stop.load(Ordering::Relaxed), "Server stopping");
    ensure!(
        request.started.elapsed() < Duration::from_secs(160),
        "Upload deadline expired before commit"
    );
    let item = lock(&owner.store)?.upload(cid, &filename, &temp, info.kind)?;
    http::json(stream, 201, &item)
}

fn item_file(owner: &Service, cid: &str, mid: &str) -> Result<File> {
    model::identifier(mid)?;
    let store = lock(&owner.store)?;
    ensure!(
        store.library.row(cid)?.items.iter().any(|i| i.id == mid),
        "Media no longer exists"
    );
    storage::regular(&store.paths.media.join(mid), storage::MAX_UPLOAD)
}

fn thumbnail(owner: &Service, stream: &mut TcpStream, cid: &str, mid: &str) -> Result<()> {
    let file = item_file(owner, cid, mid)?;
    let cached = owner
        .previews
        .lock()
        .map_err(|_| anyhow::anyhow!("Preview cache unavailable"))?
        .iter()
        .find(|(id, _)| id == mid)
        .map(|(_, bytes)| bytes.clone());
    if let Some(bytes) = cached {
        return http::reply(stream, 200, "image/png", &bytes);
    }

    let _decoder = owner
        .media_slot
        .lock()
        .map_err(|_| anyhow::anyhow!("Decoder unavailable"))?;
    let mut child = process::spawn(&mut media::command(file, "--thumbnail", (128, 80), 1)?)?;
    let mut stdout = child.0.stdout.take().context("Missing preview output")?;
    let frame = media::read_frame(
        &mut stdout,
        &owner.stop,
        Instant::now() + Duration::from_secs(15),
    )?
    .context("No preview")?;
    let mut bytes = std::io::Cursor::new(Vec::new());
    frame.pixels.write_to(&mut bytes, image::ImageFormat::Png)?;
    {
        let mut cache = owner
            .previews
            .lock()
            .map_err(|_| anyhow::anyhow!("Preview cache unavailable"))?;
        let mut size = cache.iter().map(|(_, b)| b.len()).sum::<usize>();
        while size + bytes.get_ref().len() > 2 * 1024 * 1024 {
            if let Some((_, removed)) = cache.pop_front() {
                size -= removed.len();
            } else {
                break;
            }
        }
        cache.push_back((mid.into(), bytes.get_ref().clone()));
    }
    http::reply(stream, 200, "image/png", bytes.get_ref())
}

fn download(owner: &Service, stream: &mut TcpStream, cid: &str) -> Result<()> {
    let _slot = owner
        .download
        .try_lock()
        .map_err(|_| anyhow::anyhow!("A download is already active"))?;
    let (row, paths) = {
        let store = lock(&owner.store)?;
        (store.library.row(cid)?.clone(), store.paths.clone())
    };
    ensure!(
        row.items.iter().map(|i| i.size).sum::<u64>() <= 256 * 1024 * 1024,
        "Collection exceeds 256 MiB download limit"
    );
    let mut temp = storage::Temporary::new(&paths.uploads, "upload-archive-")?;
    std::fs::remove_file(&temp.path)?; // Unlinked archive cannot survive a crash.
    let mut archive = zip::ZipWriter::new(&mut temp.file);
    let deadline = Instant::now() + Duration::from_secs(120);
    for item in row.items {
        ensure!(
            !owner.stop.load(Ordering::Relaxed) && Instant::now() < deadline,
            "Download cancelled or timed out"
        );
        model::identifier(&item.id)?;
        model::name(&item.name, 160)?;
        archive.start_file(
            format!("{}/{}", item.id, item.name),
            zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Stored),
        )?;
        let mut file = storage::regular(&paths.media.join(&item.id), storage::MAX_UPLOAD)?;
        ensure!(
            file.metadata()?.len() == item.size,
            "Media changed during download"
        );
        std::io::copy(&mut Read::by_ref(&mut file).take(item.size), &mut archive)?;
    }
    archive.finish()?;
    let length = temp.file.metadata()?.len();
    temp.file.seek(SeekFrom::Start(0))?;
    http::headers(stream, 200, "application/zip", length)?;
    let mut buffer = vec![0; 65536];
    loop {
        ensure!(
            !owner.stop.load(Ordering::Relaxed) && Instant::now() < deadline,
            "Download cancelled or timed out"
        );
        let count = temp.file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        stream.write_all(&buffer[..count])?;
    }
    Ok(())
}
