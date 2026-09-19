//! Strict metadata schema shared byte-for-byte with the Python carousel.
use crate::storage::{self, MAX_UPLOAD, Paths};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use unicode_casefold::UnicodeCaseFold;
use unicode_categories::UnicodeCategories;
use unicode_normalization::UnicodeNormalization;

pub const MAX_METADATA: u64 = 2 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Png,
    Jpeg,
    Webp,
    Gif,
    Webm,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Order {
    Ordered,
    Shuffle,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub image_seconds: u32,
    pub repeats: u32,
    pub order: Order,
    #[serde(rename = "loop")]
    pub looping: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            image_seconds: 5,
            repeats: 3,
            order: Order::Ordered,
            looping: true,
        }
    }
}

impl Settings {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            (1..=3600).contains(&self.image_seconds) && (1..=100).contains(&self.repeats),
            "Invalid duration or repeat count"
        );
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Item {
    pub id: String,
    pub name: String,
    pub kind: Kind,
    pub size: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Collection {
    pub id: String,
    pub name: String,
    pub items: Vec<Item>,
}

impl Collection {
    pub fn new(name: String) -> Self {
        Self {
            id: storage::random_id(),
            name,
            items: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Library {
    pub version: u8,
    pub collections: Vec<Collection>,
}

pub fn identifier(value: &str) -> Result<&str> {
    ensure!(
        value.len() == 32
            && value
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "Invalid internal ID"
    );
    Ok(value)
}

pub fn name(value: &str, max: usize) -> Result<String> {
    let normalized: String = value.nfc().collect();
    let value = normalized.trim();
    ensure!(
        !value.is_empty()
            && value.chars().count() <= max
            && value != "."
            && !value.contains("..")
            && !value.chars().any(|c| "/\\:".contains(c) || c.is_other()),
        "Use a short name without paths or control characters"
    );
    Ok(value.into())
}

impl Library {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.version == 1 && (1..=100).contains(&self.collections.len()),
            "Invalid library version/collection count"
        );
        let mut ids = HashSet::new();
        let mut names = HashSet::new();
        let mut count = 0;
        for row in &self.collections {
            identifier(&row.id)?;
            ensure!(
                name(&row.name, 64)? == row.name
                    && ids.insert(&row.id)
                    && names.insert(row.name.case_fold().collect::<String>()),
                "Duplicate or invalid collection"
            );
            for item in &row.items {
                identifier(&item.id)?;
                ensure!(
                    ids.insert(&item.id)
                        && name(&item.name, 160)? == item.name
                        && (1..=MAX_UPLOAD).contains(&item.size),
                    "Invalid media metadata"
                );
                count += 1;
            }
        }
        ensure!(count <= 2000, "Library capacity reached");
        Ok(())
    }

    pub fn row(&self, id: &str) -> Result<&Collection> {
        identifier(id)?;
        self.collections
            .iter()
            .find(|r| r.id == id)
            .context("Collection no longer exists")
    }

    pub fn row_mut(&mut self, id: &str) -> Result<&mut Collection> {
        identifier(id)?;
        self.collections
            .iter_mut()
            .find(|r| r.id == id)
            .context("Collection no longer exists")
    }
}

pub struct Store {
    pub paths: Paths,
    pub library: Library,
    pub settings: Settings,
    pub warning: String,
    pub revision: u64,
    _lock: std::fs::File,
}

impl Store {
    pub fn open(paths: Paths) -> Result<Self> {
        let lock = paths.lock()?;
        let path = paths.data.join("library.json");
        let (library, mut warning) = match storage::read(&path, MAX_METADATA) {
            Ok(bytes) => (serde_json::from_slice::<Library>(&bytes)?, String::new()),
            Err(e) if missing(&e) => {
                let library = Library {
                    version: 1,
                    collections: vec![Collection::new("Unsorted".into())],
                };
                let warning = storage::atomic_json(&path, &library, MAX_METADATA)?;
                (library, warning)
            }
            Err(e) => return Err(e),
        };
        library.validate()?;
        let settings = match storage::read(&paths.config.join("settings.json"), 4096) {
            Ok(bytes) => match serde_json::from_slice::<Settings>(&bytes) {
                Ok(s) if s.validate().is_ok() => s,
                _ => {
                    warning.push_str(" Invalid settings; defaults active until an explicit save.");
                    Settings::default()
                }
            },
            Err(e) if missing(&e) => Settings::default(),
            Err(e) => return Err(e.context("Unsafe/unreadable settings require local repair")),
        };
        let store = Self {
            paths,
            library,
            settings,
            warning,
            revision: 0,
            _lock: lock,
        };
        store.cleanup()?;
        Ok(store)
    }

    fn cleanup(&self) -> Result<()> {
        let live: HashSet<_> = self
            .library
            .collections
            .iter()
            .flat_map(|r| r.items.iter().map(|i| i.id.as_str()))
            .collect();
        for dir in [&self.paths.media, &self.paths.uploads] {
            for entry in std::fs::read_dir(dir)? {
                let entry = entry?;
                let filename = entry.file_name();
                let Some(filename) = filename.to_str() else {
                    continue;
                };
                if (dir == &self.paths.media
                    && identifier(filename).is_ok()
                    && !live.contains(filename))
                    || (dir == &self.paths.uploads && filename.starts_with("upload-"))
                {
                    storage::regular(&entry.path(), MAX_UPLOAD)?;
                    std::fs::remove_file(entry.path())?;
                }
            }
            storage::sync(dir)?;
        }
        Ok(())
    }

    pub fn commit(&mut self, library: Library) -> Result<()> {
        library.validate()?;
        self.warning = storage::atomic_json(
            &self.paths.data.join("library.json"),
            &library,
            MAX_METADATA,
        )?;
        self.library = library;
        self.revision += 1;
        Ok(())
    }

    pub fn save_settings(&mut self, settings: Settings) -> Result<()> {
        settings.validate()?;
        self.warning =
            storage::atomic_json(&self.paths.config.join("settings.json"), &settings, 4096)?;
        self.settings = settings;
        self.revision += 1;
        Ok(())
    }

    pub fn delete(&mut self, cid: &str, mid: Option<&str>) -> Result<()> {
        let mut next = self.library.clone();
        let row = next.row_mut(cid)?;
        if let Some(id) = mid {
            identifier(id)?;
            ensure!(
                row.items.iter().any(|i| i.id == id),
                "Media no longer exists"
            );
        }
        let doomed: Vec<_> = row
            .items
            .iter()
            .filter(|i| mid.is_none_or(|id| i.id == id))
            .cloned()
            .collect();
        for item in &doomed {
            if let Err(e) = storage::regular(&self.paths.media.join(&item.id), MAX_UPLOAD)
                && !missing(&e)
            {
                return Err(e);
            }
        }
        if let Some(id) = mid {
            row.items.retain(|i| i.id != id);
        } else {
            next.collections.retain(|r| r.id != cid);
            if next.collections.is_empty() {
                next.collections.push(Collection::new("Unsorted".into()));
            }
        }
        self.commit(next)?;
        for item in doomed {
            if let Err(e) = std::fs::remove_file(self.paths.media.join(item.id))
                && e.kind() != std::io::ErrorKind::NotFound
            {
                self.warning = "Deletion saved; orphan cleanup failed.".into();
            }
        }
        if storage::sync(&self.paths.media).is_err() {
            self.warning = "Deletion saved; directory sync failed.".into();
        }
        Ok(())
    }

    pub fn upload(
        &mut self,
        cid: &str,
        filename: &str,
        temp: &storage::Temporary,
        kind: Kind,
    ) -> Result<Item> {
        ensure!(
            temp.path.parent() == Some(self.paths.uploads.as_path())
                && temp
                    .path
                    .file_name()
                    .is_some_and(|n| n.to_string_lossy().starts_with("upload-")),
            "Invalid upload staging path"
        );
        temp.file.sync_all()?;
        let size = storage::regular(&temp.path, MAX_UPLOAD)?.metadata()?.len();
        let item = Item {
            id: storage::random_id(),
            name: name(filename, 160)?,
            kind,
            size,
        };
        let mut next = self.library.clone();
        next.row_mut(cid)?.items.push(item.clone());
        next.validate()?;
        let destination = self.paths.media.join(&item.id);
        // One atomic no-replace rename avoids a crash leaving duplicate hardlinks.
        storage::publish(&temp.path, &destination)?;
        let commit = storage::sync(&self.paths.media).and_then(|()| self.commit(next));
        if let Err(e) = commit {
            std::fs::remove_file(&destination)?;
            storage::sync(&self.paths.media)?;
            return Err(e);
        }
        Ok(item)
    }
}

fn missing(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<std::io::Error>()
        .is_some_and(|e| e.kind() == std::io::ErrorKind::NotFound)
}
