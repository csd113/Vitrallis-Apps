//! Strict single-request HTTP framing with idle and absolute deadlines.
use anyhow::{Context, Result, ensure};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{Ipv4Addr, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

pub const fn private(ip: Ipv4Addr) -> bool {
    ip.is_private() || ip.is_loopback() || ip.is_link_local()
}

pub struct Request {
    pub method: String,
    pub path: String,
    pub query: String,
    pub headers: HashMap<String, String>,
    pub started: Instant,
}

impl Request {
    pub fn parse(stream: &mut TcpStream, port: u16, stop: &AtomicBool) -> Result<Self> {
        stream.set_read_timeout(Some(Duration::from_secs(5)))?;
        stream.set_write_timeout(Some(Duration::from_secs(5)))?;
        let started = Instant::now();
        let mut bytes = Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") {
            ensure!(
                bytes.len() < 16_384
                    && started.elapsed() < Duration::from_secs(15)
                    && !stop.load(Ordering::Relaxed),
                "Header limit exceeded"
            );
            let mut byte = [0];
            stream.read_exact(&mut byte)?;
            bytes.push(byte[0]);
        }
        Self::from_header(&bytes, port, started)
    }

    pub fn from_header(bytes: &[u8], port: u16, started: Instant) -> Result<Self> {
        let text = std::str::from_utf8(bytes)?;
        let mut lines = text.split("\r\n");
        let line: Vec<_> = lines
            .next()
            .context("Missing request")?
            .split(' ')
            .collect();
        ensure!(
            line.len() == 3 && matches!(line[2], "HTTP/1.0" | "HTTP/1.1"),
            "Invalid request line"
        );
        ensure!(
            matches!(line[0], "GET" | "POST" | "PUT" | "DELETE"),
            "Unsupported method"
        );
        let (path, query) = line[1].split_once('?').unwrap_or((line[1], ""));
        ensure!(
            line[1].len() <= 2048
                && path.starts_with('/')
                && !path.starts_with("//")
                && !path.contains("..")
                && !path.contains(['%', '\\', '#'])
                && !line[1].chars().any(char::is_control),
            "Invalid request path"
        );
        let mut headers = HashMap::new();
        for line in lines.take_while(|line| !line.is_empty()) {
            let (key, value) = line.split_once(':').context("Malformed header")?;
            ensure!(
                !key.is_empty() && key.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-'),
                "Malformed header name"
            );
            ensure!(
                !value.chars().any(|c| c.is_control() && c != '\t'),
                "Malformed header value"
            );
            ensure!(
                headers
                    .insert(key.to_ascii_lowercase(), value.trim().to_owned())
                    .is_none(),
                "Duplicate header"
            );
        }
        let host = headers.get("host").context("One Host header is required")?;
        let (ip, host_port) = host
            .split_once(':')
            .context("Use the displayed IP and port")?;
        ensure!(
            private(ip.parse()?) && host_port.parse::<u16>()? == port,
            "Use the displayed IP and port"
        );
        if let Some(origin) = headers.get("origin") {
            ensure!(
                origin == &format!("http://{host}"),
                "Cross-origin requests are forbidden"
            );
        }
        ensure!(
            !headers.contains_key("transfer-encoding"),
            "Transfer-Encoding is unsupported"
        );
        Ok(Self {
            method: line[0].into(),
            path: path.into(),
            query: query.into(),
            headers,
            started,
        })
    }

    pub fn length(&self, maximum: u64) -> Result<u64> {
        let value = self
            .headers
            .get("content-length")
            .context("One Content-Length is required")?;
        ensure!(
            value.bytes().all(|b| b.is_ascii_digit()),
            "Invalid Content-Length"
        );
        let length = value.parse()?;
        ensure!(
            (1..=maximum).contains(&length),
            "Request exceeds size limit"
        );
        Ok(length)
    }

    pub fn copy_body(
        &self,
        stream: &mut TcpStream,
        output: &mut impl Write,
        maximum: u64,
        stop: &AtomicBool,
    ) -> Result<()> {
        let mut remaining = self.length(maximum)?;
        let mut buffer = vec![0; 65536];
        while remaining > 0 {
            ensure!(
                !stop.load(Ordering::Relaxed) && self.started.elapsed() < Duration::from_secs(120),
                "Transfer cancelled or timed out"
            );
            let length = buffer.len().min(usize::try_from(remaining)?);
            let count = stream.read(&mut buffer[..length])?;
            ensure!(count > 0, "Incomplete body");
            output.write_all(&buffer[..count])?;
            remaining -= u64::try_from(count)?;
        }
        Ok(())
    }

    pub fn json<T: serde::de::DeserializeOwned>(
        &self,
        stream: &mut TcpStream,
        stop: &AtomicBool,
    ) -> Result<T> {
        ensure!(
            self.headers
                .get("content-type")
                .is_some_and(|s| s == "application/json"),
            "Expected application/json"
        );
        let mut bytes = Vec::new();
        self.copy_body(stream, &mut bytes, 65536, stop)?;
        Ok(serde_json::from_slice(&bytes)?)
    }
}

pub fn filename(query: &str) -> Result<String> {
    let encoded = query
        .strip_prefix("name=")
        .context("Expected filename query")?;
    ensure!(!encoded.contains('&'), "Unexpected query parameter");
    let bytes = encoded.as_bytes();
    let mut decoded = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            let hex =
                std::str::from_utf8(bytes.get(i + 1..i + 3).context("Invalid percent escape")?)?;
            decoded.push(u8::from_str_radix(hex, 16)?);
            i += 3;
        } else {
            decoded.push(if bytes[i] == b'+' { b' ' } else { bytes[i] });
            i += 1;
        }
    }
    crate::model::name(&String::from_utf8(decoded)?, 160)
}

pub fn headers(stream: &mut TcpStream, status: u16, mime: &str, length: u64) -> Result<()> {
    write!(
        stream,
        "HTTP/1.0 {status} Response\r\nContent-Type: {mime}\r\nContent-Length: {length}\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'\r\n\r\n"
    )?;
    Ok(())
}

pub fn reply(stream: &mut TcpStream, status: u16, mime: &str, bytes: &[u8]) -> Result<()> {
    headers(stream, status, mime, u64::try_from(bytes.len())?)?;
    stream.write_all(bytes)?;
    Ok(())
}

pub fn json(stream: &mut TcpStream, status: u16, value: &impl serde::Serialize) -> Result<()> {
    reply(
        stream,
        status,
        "application/json; charset=utf-8",
        &serde_json::to_vec(value)?,
    )
}
