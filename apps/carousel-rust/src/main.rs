//! Carousel-Rust application entry and isolated decoder dispatch.
mod compositor;
mod http;
mod media;
mod model;
mod player;
mod process;
mod render;
mod server;
mod storage;
mod support;
mod ui;

fn main() -> anyhow::Result<()> {
    let arguments: Vec<_> = std::env::args().skip(1).collect();
    if arguments
        .first()
        .is_some_and(|a| matches!(a.as_str(), "--decode" | "--inspect" | "--thumbnail"))
    {
        return media::child(&arguments);
    }
    if arguments == ["--help"] {
        println!(
            "Carousel-Rust: [--software-dev] [--play-first] [--smoke-seconds N] [--screenshot /absolute/new.png]"
        );
        return Ok(());
    }
    let options = options(&arguments)?;
    let stop = process::stopped();
    for signal in [
        signal_hook::consts::SIGTERM,
        signal_hook::consts::SIGINT,
        signal_hook::consts::SIGHUP,
    ] {
        signal_hook::flag::register(signal, std::sync::Arc::clone(&stop))?;
    }
    let executable = std::env::current_exe()?;
    let package = if executable.file_name().is_some_and(|s| s == "app") {
        executable
            .ancestors()
            .nth(3)
            .ok_or_else(|| anyhow::anyhow!("Invalid installed binary path"))?
    } else {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
    };
    if let Some(path) = &options.screenshot {
        anyhow::ensure!(
            path.is_absolute() && !path.starts_with(package),
            "Screenshot must be absolute and outside the package"
        );
        storage::directory(
            path.parent()
                .ok_or_else(|| anyhow::anyhow!("Missing screenshot parent"))?,
            false,
        )?;
    }
    let store = model::Store::open(storage::Paths::from_env(package)?)?;
    let shared = std::sync::Arc::new(std::sync::Mutex::new(store));
    let server = server::Server::start(shared, stop, "0.0.0.0", 8765)?;
    ui::run(
        &server.service,
        options.software,
        options.seconds,
        options.play_first,
        options.screenshot.as_deref(),
    )
}

#[cfg(test)]
#[path = "../tests/unit.rs"]
mod tests;

#[derive(Default)]
struct Options {
    software: bool,
    play_first: bool,
    seconds: Option<u64>,
    screenshot: Option<std::path::PathBuf>,
}

fn options(arguments: &[String]) -> anyhow::Result<Options> {
    let mut options = Options::default();
    let mut values = arguments.iter();
    while let Some(value) = values.next() {
        match value.as_str() {
            "--software-dev" => options.software = true,
            "--play-first" => options.play_first = true,
            "--smoke-seconds" => {
                let seconds = values
                    .next()
                    .ok_or_else(|| anyhow::anyhow!("Missing smoke duration"))?
                    .parse()?;
                anyhow::ensure!(
                    (1..=3600).contains(&seconds),
                    "Smoke duration must be 1–3600 seconds"
                );
                options.seconds = Some(seconds);
            }
            "--screenshot" => {
                options.screenshot = Some(
                    values
                        .next()
                        .ok_or_else(|| anyhow::anyhow!("Missing screenshot path"))?
                        .into(),
                );
            }
            _ => anyhow::bail!("Unknown option; use --help"),
        }
    }
    Ok(options)
}
