//! A display-free packaging probe; graphical Rust apps must follow the rendering contract.
use std::{env, fs, io, path::PathBuf};

fn greeting_path() -> io::Result<PathBuf> {
    let executable = env::current_exe()?;
    let package = executable
        .parent()
        .and_then(std::path::Path::parent)
        .and_then(std::path::Path::parent)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "invalid package location"))?;
    Ok(package.join("assets/greeting.txt"))
}

fn main() -> io::Result<()> {
    let text = fs::read_to_string(greeting_path()?)?;
    println!("{}", text.trim());
    Ok(())
}
