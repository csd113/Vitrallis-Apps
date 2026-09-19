//! Shared Python-compatible POSIX storage and durable replacement.
use anyhow::{Context, Result, bail, ensure};
use std::fs::{self, DirBuilder, File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Component, Path, PathBuf};

pub const SHARED_ID: &str = "io.vitrallis.mediacarousel";
pub const MAX_UPLOAD: u64 = 64 * 1024 * 1024;

pub fn uid() -> u32 {
    // SAFETY: getuid has no arguments or memory preconditions.
    unsafe { libc::getuid() }
}

pub fn directory(path: &Path, private: bool) -> Result<()> {
    ensure!(path.is_absolute(), "Storage paths must be absolute");
    let mut current = PathBuf::new();
    for part in path.components() {
        ensure!(!matches!(part, Component::ParentDir), "Storage traversal");
        current.push(part);
        let info = fs::symlink_metadata(&current)?;
        ensure!(info.is_dir(), "Storage contains a link or non-directory");
    }
    if private {
        let info = fs::symlink_metadata(path)?;
        ensure!(
            info.uid() == uid() && info.mode().trailing_zeros() >= 6,
            "Storage must be owned by this user and mode 0700"
        );
    }
    Ok(())
}

fn check_root(path: &Path, package: &Path) -> Result<()> {
    ensure!(
        path.is_absolute() && !path.starts_with(package),
        "Storage must be absolute and outside the package"
    );
    ensure!(
        !path.components().any(|c| matches!(c, Component::ParentDir)),
        "Storage traversal"
    );
    let mut ancestor = path;
    loop {
        match fs::symlink_metadata(ancestor) {
            Ok(_) => return directory(ancestor, ancestor == path),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                ancestor = ancestor.parent().context("Missing storage ancestor")?;
            }
            Err(e) => return Err(e.into()),
        }
    }
}

fn make_private(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Ok(_) => directory(path, false),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            make_private(path.parent().context("Missing parent")?)?;
            DirBuilder::new().mode(0o700).create(path)?;
            directory(path, false)
        }
        Err(e) => Err(e.into()),
    }
}

#[derive(Clone, Debug)]
pub struct Paths {
    pub config: PathBuf,
    pub data: PathBuf,
    pub media: PathBuf,
    pub uploads: PathBuf,
}

impl Paths {
    pub fn from_env(package: &Path) -> Result<Self> {
        let home = PathBuf::from(std::env::var_os("HOME").context("HOME is required")?);
        directory(&home, false)?;
        let root = |key, fallback: &str| {
            std::env::var_os(key)
                .map_or_else(|| home.join(fallback), PathBuf::from)
                .join(SHARED_ID)
        };
        Self::create(
            root("XDG_CONFIG_HOME", ".config"),
            root("XDG_DATA_HOME", ".local/share"),
            &root("XDG_CACHE_HOME", ".cache"),
            package,
        )
    }

    pub fn create(config: PathBuf, data: PathBuf, cache: &Path, package: &Path) -> Result<Self> {
        let paths = Self {
            media: data.join("media"),
            uploads: data.join("uploads"),
            config,
            data,
        };
        let directories = [
            &paths.config,
            &paths.data,
            cache,
            &paths.media,
            &paths.uploads,
        ];
        // Validate ALL configured roots before the first mutation.
        for path in directories {
            check_root(path, package)?;
        }
        for path in directories {
            make_private(path)?;
            directory(path, true)?;
        }
        Ok(paths)
    }

    pub fn lock(&self) -> Result<File> {
        directory(&self.data, true)?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(self.data.join("instance.lock"))?;
        check_file(&file, 4096)?;
        // File::try_lock uses flock on Unix, matching Python's fcntl.flock.
        file.try_lock()
            .context("Close the Python or Rust carousel before opening another instance")?;
        Ok(file)
    }
}

fn check_file(file: &File, limit: u64) -> Result<()> {
    let info = file.metadata()?;
    ensure!(
        info.is_file() && info.nlink() == 1 && info.uid() == uid() && info.len() <= limit,
        "Unsafe or oversized data file"
    );
    Ok(())
}

pub fn regular(path: &Path, limit: u64) -> Result<File> {
    directory(path.parent().context("Missing parent")?, true)?;
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    check_file(&file, limit)?;
    Ok(file)
}

pub fn read(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    regular(path, limit)?
        .take(limit + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        u64::try_from(bytes.len())? <= limit,
        "File grew beyond limit"
    );
    Ok(bytes)
}

pub fn random_id() -> String {
    format!("{:032x}", rand::random::<u128>())
}

pub struct Temporary {
    pub path: PathBuf,
    pub file: File,
}

impl Temporary {
    pub fn new(parent: &Path, prefix: &str) -> Result<Self> {
        directory(parent, true)?;
        for _ in 0..8 {
            let path = parent.join(format!("{prefix}{}", random_id()));
            match OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&path)
            {
                Ok(file) => return Ok(Self { path, file }),
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => (),
                Err(e) => return Err(e.into()),
            }
        }
        bail!("Temporary file collision")
    }
}

impl Drop for Temporary {
    fn drop(&mut self) {
        if let Err(e) = fs::remove_file(&self.path)
            && e.kind() != std::io::ErrorKind::NotFound
        {
            eprintln!("event=cleanup_failed error={e}");
        }
    }
}

pub fn sync(path: &Path) -> Result<()> {
    directory(path, true)?;
    File::open(path)?.sync_all()?;
    Ok(())
}

pub fn atomic_json<T: serde::Serialize>(path: &Path, value: &T, limit: u64) -> Result<String> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    ensure!(
        u64::try_from(bytes.len())? <= limit,
        "Metadata capacity reached"
    );
    match fs::symlink_metadata(path) {
        Ok(_) => {
            regular(path, limit)?;
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
        Err(e) => return Err(e.into()),
    }
    let parent = path.parent().context("Missing parent")?;
    let mut temp = Temporary::new(parent, ".write-")?;
    temp.file.write_all(&bytes)?;
    temp.file.sync_all()?;
    fs::rename(&temp.path, path)?;
    // Rename is the commit point. A later fsync failure must not roll back memory.
    Ok(match sync(parent) {
        Ok(()) => String::new(),
        Err(_) => "Saved, but directory sync failed; power-loss durability is uncertain.".into(),
    })
}

/// Atomically publish a staged file without replacing a concurrent destination.
pub fn publish(source: &Path, destination: &Path) -> Result<()> {
    use std::os::unix::ffi::OsStrExt;
    directory(source.parent().context("Missing source parent")?, true)?;
    directory(
        destination.parent().context("Missing destination parent")?,
        true,
    )?;
    let source = std::ffi::CString::new(source.as_os_str().as_bytes())?;
    let destination = std::ffi::CString::new(destination.as_os_str().as_bytes())?;
    #[cfg(target_os = "linux")]
    // SAFETY: valid NUL-terminated paths; no-replace rename has no pointer writes.
    let result = unsafe {
        libc::renameat2(
            libc::AT_FDCWD,
            source.as_ptr(),
            libc::AT_FDCWD,
            destination.as_ptr(),
            libc::RENAME_NOREPLACE,
        )
    };
    #[cfg(target_os = "macos")]
    // SAFETY: valid NUL-terminated paths; RENAME_EXCL forbids replacement.
    let result =
        unsafe { libc::renamex_np(source.as_ptr(), destination.as_ptr(), libc::RENAME_EXCL) };
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    let result = -1;
    ensure!(
        result == 0,
        "Cannot publish staged file: {}",
        std::io::Error::last_os_error()
    );
    Ok(())
}
