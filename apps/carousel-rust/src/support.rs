//! Local address discovery, real decoder probes, and explicit platform installer.
use crate::{
    media, process,
    server::{self, Service},
    storage,
};
use anyhow::{Result, ensure};
use serde_json::json;
use std::io::{Read, Write};
use std::net::Ipv4Addr;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::time::Duration;

const HELPER: &str = "/usr/local/libexec/vitrallis-carousel-install-media";

pub fn urls(port: u16) -> Vec<String> {
    let mut command = if cfg!(target_os = "linux") {
        let mut c = Command::new("hostname");
        c.arg("-I");
        c
    } else {
        Command::new("ifconfig")
    };
    command.stdin(Stdio::null());
    let bytes = process::capture(
        &mut command,
        16384,
        Duration::from_secs(2),
        &AtomicBool::new(false),
    )
    .unwrap_or_default();
    let mut addresses = Vec::new();
    for ip in String::from_utf8_lossy(&bytes)
        .split_whitespace()
        .filter_map(|s| s.parse::<Ipv4Addr>().ok())
        .take(128)
    {
        if ip.is_private() && !ip.is_loopback() && !ip.is_link_local() {
            let url = format!("http://{ip}:{port}");
            if !addresses.contains(&url) {
                addresses.push(url);
            }
        }
    }
    if addresses.is_empty() {
        addresses.push(format!("http://127.0.0.1:{port}"));
    }
    addresses
}

pub fn helper_ready() -> bool {
    let helper = Path::new(HELPER);
    for path in helper.ancestors() {
        let Ok(info) = std::fs::symlink_metadata(path) else {
            return false;
        };
        if info.uid() != 0 || info.mode() & 0o022 != 0 || info.file_type().is_symlink() {
            return false;
        }
        if path == helper && (!info.is_file() || info.mode() & 0o111 == 0) {
            return false;
        }
    }
    true
}

fn probe(owner: &Service, bytes: &[u8]) -> bool {
    let run = || -> Result<()> {
        let paths = server::lock(&owner.store)?.paths.clone();
        let mut temp = storage::Temporary::new(&paths.uploads, "upload-probe-")?;
        temp.file.write_all(bytes)?;
        temp.file.sync_all()?;
        media::isolated_inspect(
            storage::regular(&temp.path, storage::MAX_UPLOAD)?,
            &owner.stop,
        )?;
        Ok(())
    };
    run().is_ok()
}

pub fn refresh(owner: &Service) {
    let Ok(_slot) = owner.media_slot.lock() else {
        return;
    };
    let vp8 = probe(owner, include_bytes!("../assets/capability-vp8.webm"));
    let vp9 = probe(owner, include_bytes!("../assets/capability-vp9.webm"));
    let webp = probe(owner, include_bytes!("../assets/capability.webp"));
    if let Ok(mut capabilities) = owner.capabilities.lock() {
        *capabilities = json!({"ready":vp8 && vp9 && webp,"webm":vp8 || vp9,"vp8":vp8,"vp9":vp9,"webp":webp,
            "webm_note":if vp8 && vp9 { "VP8/VP9 verified. AV1 depends on system FFmpeg." } else { "Provide system ffmpeg and ffprobe with WebM decoders." }});
    }
    if let Ok(mut state) = owner.installation.lock() {
        state["available"] = json!(helper_ready());
        if state["status"] == "idle" {
            state["message"] = json!(if helper_ready() {
                ""
            } else {
                "Administrator setup is required for the multimedia installer."
            });
        }
    }
}

pub fn install(owner: &Arc<Service>) -> Result<serde_json::Value> {
    ensure!(
        helper_ready(),
        "The platform multimedia installer is not configured"
    );
    let mut state = owner
        .installation
        .lock()
        .map_err(|_| anyhow::anyhow!("Installer unavailable"))?;
    if state["status"] == "running" {
        return Ok(state.clone());
    }
    *state = json!({"status":"running","available":true,"message":"Rechecking decoders before installing Debian FFmpeg…"});
    let service = Arc::clone(owner);
    std::thread::spawn(move || {
        refresh(&service);
        let ready = service
            .capabilities
            .lock()
            .is_ok_and(|c| c["ready"] == true);
        let result = if ready { Ok(()) } else { run_installer() };
        refresh(&service);
        let ready = service
            .capabilities
            .lock()
            .is_ok_and(|c| c["ready"] == true);
        if let Ok(mut state) = service.installation.lock() {
            *state = match result {
                Ok(()) if ready => {
                    json!({"status":"ready","available":true,"message":"VP8/VP9 and static WebP decoding verified."})
                }
                Ok(()) => {
                    json!({"status":"failed","available":true,"message":"Installation finished but decoder probes failed."})
                }
                Err(e) => json!({"status":"failed","available":true,"message":e.to_string()}),
            };
        }
    });
    Ok(state.clone())
}

fn run_installer() -> Result<()> {
    ensure!(helper_ready(), "Unsafe multimedia helper");
    // No user arguments, no shell, no package-manager termination during shutdown.
    let mut child = Command::new("/usr/bin/sudo")
        .args(["-n", HELPER])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()?;
    let mut tail = Vec::new();
    if let Some(mut stderr) = child.stderr.take() {
        let mut buffer = [0; 4096];
        loop {
            let count = stderr.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            tail.extend_from_slice(&buffer[..count]);
            if tail.len() > 2000 {
                tail.drain(..tail.len() - 2000);
            }
        }
    }
    ensure!(
        child.wait()?.success(),
        "Multimedia installation failed: {}",
        String::from_utf8_lossy(&tail)
    );
    Ok(())
}
