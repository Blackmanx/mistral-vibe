//! Clipboard-image ingestion and composer token insertion.

use std::fs;
use std::fs::File;
use std::io::{Read, Seek, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use tempfile::Builder;
use tokio::sync::mpsc::Sender;

use crate::app::{App, Status, ToastSeverity};
use crate::{chat_input, paste_files, paste_path};

mod store;

pub use store::{clipboard_image_path, write_clipboard_image, write_clipboard_image_as};

pub const PNG_MAGIC: &[u8] = b"\x89PNG\r\n\x1a\n";
pub const MAX_IMAGE_BYTES: usize = 10 * 1024 * 1024;
pub const CHANNEL_CAP: usize = 8;
const READ_TIMEOUT: Duration = Duration::from_secs(5);
const WSL_READ_TIMEOUT: Duration = Duration::from_secs(20);
const WARNING_SECS: u64 = 5;

/// Read the Windows clipboard image through WSL interop. `OpenStandardOutput`
/// bypasses PowerShell's text encoding so the PNG bytes arrive intact.
const POWERSHELL_IMAGE_SCRIPT: &str = "Add-Type -AssemblyName System.Windows.Forms; \
Add-Type -AssemblyName System.Drawing; \
$img = [System.Windows.Forms.Clipboard]::GetImage(); \
if ($img -ne $null) { \
  $ms = New-Object System.IO.MemoryStream; \
  $img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); \
  $out = [Console]::OpenStandardOutput(); \
  $bytes = $ms.ToArray(); \
  $out.Write($bytes, 0, $bytes.Length); \
  $out.Flush() \
}";

#[derive(Default)]
pub struct State {
    pub tx: Option<Sender<Event>>,
    pub in_flight: usize,
}

impl State {
    pub fn has_slot(&self) -> bool {
        self.tx.is_some() && self.in_flight < CHANNEL_CAP
    }
}

pub enum Event {
    Empty {
        notify: bool,
    },
    TooLarge(usize),
    Failed,
    Pasted {
        path: PathBuf,
    },
    ImageFiles(Vec<PathBuf>),
    Probed {
        start: usize,
        raw: String,
        paths: Option<Vec<String>>,
    },
}

pub fn is_supported() -> bool {
    cfg!(any(target_os = "macos", target_os = "linux"))
}

pub fn is_paste_image_key(key: &KeyEvent, supported: bool) -> bool {
    supported
        && ((key.modifiers == KeyModifiers::ALT && key.code == KeyCode::Char('v'))
            || (key
                .modifiers
                .contains(KeyModifiers::CONTROL | KeyModifiers::SHIFT)
                && matches!(key.code, KeyCode::Char('v') | KeyCode::Char('V')))
            || (cfg!(target_os = "macos")
                && key.modifiers == KeyModifiers::CONTROL
                && key.code == KeyCode::Char('v')))
}

pub fn request(app: &mut App, notify_when_empty: bool) {
    if is_supported() {
        paste_files::spawn_job(
            app,
            move || read_and_store(notify_when_empty),
            Event::Failed,
        );
    }
}

pub fn apply_event(app: &mut App, event: Event) {
    app.paste_image.in_flight = app.paste_image.in_flight.saturating_sub(1);
    match event {
        Event::Empty { notify: false } => {}
        Event::Empty { notify: true } => {
            let message = if is_wsl() {
                "No image on the Windows clipboard. Enable WSL interop (powershell.exe) or WSLg."
            } else {
                "No image found on the clipboard."
            };
            app.show_toast(message.to_owned(), ToastSeverity::Warning, 5);
        }
        Event::TooLarge(size) => app.show_toast(
            format!(
                "Clipboard image is {}; max is {}.",
                natural_size(size),
                natural_size(MAX_IMAGE_BYTES)
            ),
            ToastSeverity::Warning,
            WARNING_SECS,
        ),
        Event::Failed => app.show_toast(
            "Failed to save pasted image to disk.".to_owned(),
            ToastSeverity::Warning,
            WARNING_SECS,
        ),
        Event::Pasted { path } => paste_files::apply_image_files(app, vec![path]),
        Event::ImageFiles(paths) => paste_files::apply_image_files(app, paths),
        Event::Probed { start, raw, paths } => paste_files::apply_probed(app, start, &raw, paths),
    }
}

/// Warn and return true when the active model cannot take images.
pub(crate) fn rejects_images(app: &mut App) -> bool {
    if app.session.startup_config.images_supported || matches!(app.session.status, Status::Starting)
    {
        return false;
    }
    let name = &app.session.startup_config.active_model_display_name;
    app.show_toast(
        format!(
            "Model `{name}` does not support images. Switch with /model or ask me to enable image support for this model."
        ),
        ToastSeverity::Warning,
        WARNING_SECS,
    );
    true
}

// Finder copies also carry the file icon as an image, so file URLs win.
fn read_and_store(notify: bool) -> Event {
    let files = paste_files::read_clipboard_files();
    if !files.is_empty() {
        let images = paste_files::image_files(files);
        return match images.is_empty() {
            true => Event::Empty { notify },
            false => Event::ImageFiles(images),
        };
    }
    let Some((data, ext)) = read_clipboard_image() else {
        return Event::Empty { notify };
    };
    if data.len() > MAX_IMAGE_BYTES {
        return Event::TooLarge(data.len());
    }
    match write_clipboard_image_as(&data, ext) {
        Ok(path) => Event::Pasted { path },
        Err(error) => {
            tracing::warn!(%error, "failed to write pasted clipboard image");
            Event::Failed
        }
    }
}

pub fn read_clipboard_image() -> Option<(Vec<u8>, &'static str)> {
    if cfg!(target_os = "macos") {
        return read_macos().map(|data| (data, "png"));
    }
    if cfg!(target_os = "linux") {
        return read_linux();
    }
    None
}

fn read_macos() -> Option<Vec<u8>> {
    if let Some(data) = read_macos_class("PNGf") {
        return Some(data);
    }
    let tiff = read_macos_class("TIFF")?;
    convert_to_png_via_sips(&tiff)
}

fn read_macos_class(four_cc: &str) -> Option<Vec<u8>> {
    let mut file = Builder::new().suffix(".bin").tempfile().ok()?;
    file.flush().ok()?;
    let path = applescript_string(file.path());
    let script = format!(
        "set targetFile to POSIX file \"{path}\"\ntry\n    set imgData to the clipboard as «class {four_cc}»\non error\n    return\nend try\nset fh to open for access targetFile with write permission\nset eof of fh to 0\nwrite imgData to fh\nclose access fh\n"
    );
    let mut command = Command::new("osascript");
    command.args(["-e", &script]);
    if !run_with_timeout(&mut command, Stdio::null()) {
        return None;
    }
    fs::read(file.path()).ok().filter(|data| !data.is_empty())
}

fn convert_to_png_via_sips(data: &[u8]) -> Option<Vec<u8>> {
    let mut source = Builder::new().suffix(".tiff").tempfile().ok()?;
    source.write_all(data).ok()?;
    source.flush().ok()?;
    let output = Builder::new().suffix(".png").tempfile().ok()?;
    let output_path = output.into_temp_path();
    fs::remove_file(&output_path).ok()?;
    let mut command = Command::new("sips");
    command.args([
        "-s",
        "format",
        "png",
        source.path().to_str()?,
        "--out",
        output_path.to_str()?,
    ]);
    if !run_with_timeout(&mut command, Stdio::null()) {
        return None;
    }
    fs::read(&output_path)
        .ok()
        .filter(|bytes| bytes.starts_with(PNG_MAGIC))
}

fn read_linux() -> Option<(Vec<u8>, &'static str)> {
    // WSLg's clipboard bridge is local and cheap; only fall back to Windows
    // interop when it has no image or is not running.
    if std::env::var_os("WAYLAND_DISPLAY").is_some() {
        if let Some(image) = read_wayland() {
            return Some(image);
        }
    }
    if std::env::var_os("DISPLAY").is_some() {
        if let Some(image) = read_x11() {
            return Some(image);
        }
    }
    if is_wsl() {
        return read_wsl();
    }
    None
}

fn is_wsl() -> bool {
    std::env::var_os("WSL_DISTRO_NAME").is_some() || std::env::var_os("WSL_INTEROP").is_some()
}

fn read_wsl() -> Option<(Vec<u8>, &'static str)> {
    let program = wsl_powershell()?;
    let data = read_command_with_timeout(
        program.to_str()?,
        &[
            "-NoProfile",
            "-NoLogo",
            "-NonInteractive",
            "-STA",
            "-Command",
            POWERSHELL_IMAGE_SCRIPT,
        ],
        WSL_READ_TIMEOUT,
    )?;
    let ext = detect_image_extension(&data)?;
    Some((data, ext))
}

fn wsl_powershell() -> Option<PathBuf> {
    for name in ["powershell.exe", "pwsh.exe"] {
        if let Some(path) = std::env::split_paths(&std::env::var_os("PATH")?)
            .map(|dir| dir.join(name))
            .find(|path| path.is_file())
        {
            return Some(path);
        }
    }
    let fallback = Path::new("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe");
    fallback.is_file().then(|| fallback.to_path_buf())
}

fn read_wayland() -> Option<(Vec<u8>, &'static str)> {
    let types = read_command("wl-paste", &["--list-types"])?;
    let (mime, ext) = pick_image_mime(std::str::from_utf8(&types).ok()?)?;
    let data = read_command("wl-paste", &["--no-newline", "--type", mime])?;
    if ext == "bmp" {
        return convert_bmp_to_png(&data).map(|png| (png, "png"));
    }
    let detected = detect_image_extension(&data).unwrap_or(ext);
    Some((data, detected))
}

fn read_x11() -> Option<(Vec<u8>, &'static str)> {
    let targets = read_command("xclip", &["-selection", "clipboard", "-t", "TARGETS", "-o"])?;
    let (mime, ext) = pick_image_mime(std::str::from_utf8(&targets).ok()?)?;
    let data = read_command("xclip", &["-selection", "clipboard", "-t", mime, "-o"])
        .or_else(|| read_command("xsel", &["--clipboard", "--output", "--target", mime]))?;
    if ext == "bmp" {
        return convert_bmp_to_png(&data).map(|png| (png, "png"));
    }
    let detected = detect_image_extension(&data).unwrap_or(ext);
    Some((data, detected))
}

/// Run a clipboard helper with the same timeout as the macOS path, returning stdout.
fn read_command(program: &str, args: &[&str]) -> Option<Vec<u8>> {
    read_command_with_timeout(program, args, READ_TIMEOUT)
}

fn read_command_with_timeout(program: &str, args: &[&str], timeout: Duration) -> Option<Vec<u8>> {
    let mut output: File = tempfile::tempfile().ok()?;
    let mut command = Command::new(program);
    command.args(args);
    if !run_with_timeout_for(&mut command, Stdio::from(output.try_clone().ok()?), timeout) {
        return None;
    }
    output.rewind().ok()?;
    let mut data = Vec::new();
    output.read_to_end(&mut data).ok()?;
    (!data.is_empty()).then_some(data)
}

/// `wl-paste`/`xclip` list many text targets; prefer the formats the session accepts.
fn convert_bmp_to_png(data: &[u8]) -> Option<Vec<u8>> {
    let mut input = Builder::new().suffix(".bmp").tempfile().ok()?;
    input.write_all(data).ok()?;
    input.flush().ok()?;
    let output = Builder::new().suffix(".png").tempfile().ok()?;
    let output_path = output.into_temp_path();
    fs::remove_file(&output_path).ok()?;
    let mut command = Command::new("convert");
    command.args([input.path().to_str()?, output_path.to_str()?]);
    if !run_with_timeout(&mut command, Stdio::null()) {
        return None;
    }
    fs::read(&output_path)
        .ok()
        .filter(|bytes| bytes.starts_with(PNG_MAGIC))
}

fn pick_image_mime(targets: &str) -> Option<(&'static str, &'static str)> {
    const MIMES: [(&str, &str); 5] = [
        ("image/png", "png"),
        ("image/jpeg", "jpg"),
        ("image/webp", "webp"),
        ("image/gif", "gif"),
        ("image/bmp", "bmp"),
    ];
    MIMES.into_iter().find(|(mime, _)| {
        targets
            .lines()
            .any(|line| line.trim().eq_ignore_ascii_case(mime))
    })
}

fn detect_image_extension(data: &[u8]) -> Option<&'static str> {
    if data.starts_with(PNG_MAGIC) {
        return Some("png");
    }
    if data.starts_with(&[0xff, 0xd8, 0xff]) {
        return Some("jpg");
    }
    if data.len() >= 12 && data.starts_with(b"RIFF") && &data[8..12] == b"WEBP" {
        return Some("webp");
    }
    if data.starts_with(b"GIF8") {
        return Some("gif");
    }
    if data.starts_with(b"BM") {
        return Some("bmp");
    }
    None
}

pub(crate) fn run_with_timeout(command: &mut Command, stdout: Stdio) -> bool {
    run_with_timeout_for(command, stdout, READ_TIMEOUT)
}

fn run_with_timeout_for(command: &mut Command, stdout: Stdio, timeout: Duration) -> bool {
    let Ok(mut child) = command.stdout(stdout).stderr(Stdio::null()).spawn() else {
        return false;
    };
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return status.success(),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return false;
            }
        }
    }
}

/// Insert an image token at the caret, spaced from its neighbours, and return its byte span.
pub fn insert_image_token(
    input: &mut String,
    cursor: &mut usize,
    anchor: &mut Option<usize>,
    token: &str,
) -> (usize, usize) {
    if let Some((lo, hi)) = chat_input::selection_range(input, *cursor, *anchor) {
        input.replace_range(lo..hi, "");
        *cursor = lo;
    }
    *anchor = None;
    let insertion = paste_path::with_image_mention_boundaries(input, *cursor, token);
    let start = *cursor + insertion.find(token).unwrap_or_default();
    crate::utils::input_edit::insert(input, cursor, &insertion);
    (start, start + token.len())
}

fn applescript_string(path: &Path) -> String {
    path.to_string_lossy()
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
}

fn natural_size(bytes: usize) -> String {
    if bytes < 1024 {
        return format!("{bytes} Bytes");
    }
    let mut value = bytes as f64;
    let mut unit = "Bytes";
    for next in ["KiB", "MiB", "GiB"] {
        value /= 1024.0;
        unit = next;
        if value < 1024.0 {
            break;
        }
    }
    format!("{value:.1} {unit}")
}
