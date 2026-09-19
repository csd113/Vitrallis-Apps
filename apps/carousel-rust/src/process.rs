//! Owned, bounded subprocess groups. No shell interpolation.
use anyhow::{Context, Result, bail, ensure};
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;
use std::process::{Child, Command, Stdio};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::time::{Duration, Instant};

pub struct Group(pub Child, bool);

impl Drop for Group {
    fn drop(&mut self) {
        if self.1
            && let Ok(pid) = i32::try_from(self.0.id())
        {
            // SAFETY: negative PID targets only this child's newly created group.
            unsafe {
                libc::kill(-pid, libc::SIGKILL);
            }
        }
        if !self.1 {
            let _ = self.0.kill();
        }
        if let Err(e) = self.0.wait() {
            eprintln!("event=child_reap_failed error={e}");
        }
    }
}

pub fn spawn(command: &mut Command) -> Result<Group> {
    Ok(Group(
        command
            .process_group(0)
            .stderr(Stdio::null())
            .stdout(Stdio::piped())
            .spawn()?,
        true,
    ))
}

pub fn read_exact<R: Read + AsRawFd>(
    reader: &mut R,
    buffer: &mut [u8],
    cancel: &AtomicBool,
    deadline: Instant,
) -> Result<bool> {
    let mut offset = 0;
    let mut progress = Instant::now();
    while offset < buffer.len() {
        ensure!(!cancel.load(Ordering::Relaxed), "Cancelled");
        ensure!(
            Instant::now() < deadline && progress.elapsed() < Duration::from_secs(10),
            "Decoder timed out"
        );
        let mut descriptor = libc::pollfd {
            fd: reader.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: one valid pollfd, live reader descriptor, bounded timeout.
        let ready = unsafe { libc::poll(&raw mut descriptor, 1, 100) };
        if ready < 0 {
            let e = std::io::Error::last_os_error();
            if e.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(e.into());
        }
        if ready == 0 {
            continue;
        }
        let count = reader.read(&mut buffer[offset..])?;
        if count == 0 {
            ensure!(offset == 0, "Truncated decoder output");
            return Ok(false);
        }
        offset += count;
        progress = Instant::now();
    }
    Ok(true)
}

pub fn capture(
    command: &mut Command,
    limit: usize,
    timeout: Duration,
    cancel: &AtomicBool,
) -> Result<Vec<u8>> {
    capture_output(spawn(command)?, limit, timeout, cancel)
}

pub fn capture_in_group(
    command: &mut Command,
    limit: usize,
    timeout: Duration,
    cancel: &AtomicBool,
) -> Result<Vec<u8>> {
    let child = Group(
        command
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?,
        false,
    );
    capture_output(child, limit, timeout, cancel)
}

fn capture_output(
    mut child: Group,
    limit: usize,
    timeout: Duration,
    cancel: &AtomicBool,
) -> Result<Vec<u8>> {
    let mut output = child.0.stdout.take().context("Missing child stdout")?;
    let deadline = Instant::now() + timeout;
    let mut bytes = Vec::new();
    let mut byte = [0];
    while read_exact(&mut output, &mut byte, cancel, deadline)? {
        ensure!(bytes.len() < limit, "Child output exceeds limit");
        bytes.push(byte[0]);
    }
    loop {
        if let Some(status) = child.0.try_wait()? {
            ensure!(status.success(), "Decoder/process failed");
            return Ok(bytes);
        }
        if cancel.load(Ordering::Relaxed) || Instant::now() >= deadline {
            bail!("Child did not exit");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[cfg(target_os = "linux")]
pub fn limits(validation: bool) -> Result<()> {
    {
        let space = libc::rlimit {
            rlim_cur: 256 * 1024 * 1024,
            rlim_max: 256 * 1024 * 1024,
        };
        // SAFETY: valid rlimit pointer; applies only within the isolated child.
        ensure!(
            unsafe { libc::setrlimit(libc::RLIMIT_AS, &raw const space) } == 0,
            "Cannot limit decoder memory"
        );
        if validation {
            let cpu = libc::rlimit {
                rlim_cur: 30,
                rlim_max: 30,
            };
            // SAFETY: valid rlimit pointer; child-only CPU limit.
            ensure!(
                unsafe { libc::setrlimit(libc::RLIMIT_CPU, &raw const cpu) } == 0,
                "Cannot limit decoder CPU"
            );
        }
    }
    Ok(())
}

pub fn stopped() -> Arc<AtomicBool> {
    Arc::new(AtomicBool::new(false))
}
