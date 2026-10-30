//! `/update`: rebuild and reinstall this fork from its GitHub `main`.

use std::process::Stdio;
use std::time::Duration;

use super::event::{dispatch, CommandEvent};
use crate::app::App;

/// The same one-line installer the fork's README documents.
const INSTALLER: &str =
    "curl -fsSL https://raw.githubusercontent.com/Blackmanx/mistral-vibe/main/install.sh | bash";

/// A rebuild compiles the Rust client and the Harness; give it room.
const UPDATE_TIMEOUT: Duration = Duration::from_secs(30 * 60);

/// The last lines worth keeping for the transcript when something fails.
const OUTPUT_TAIL_LINES: usize = 4;

pub(super) fn run(app: &mut App) {
    let Some((_session, tx)) = dispatch(app) else {
        return;
    };
    tokio::spawn(async move {
        let event = match run_installer().await {
            Ok(()) => CommandEvent::Status(
                "Vibe rebuilt and reinstalled from the fork. Restart it to run the new build."
                    .to_owned(),
            ),
            Err(message) => CommandEvent::Error(message),
        };
        let _ = tx.try_send(event);
    });
}

/// Run the installer to completion. The current process keeps running the old
/// build until the user restarts it; replacing the files underneath is safe.
async fn run_installer() -> Result<(), String> {
    let run = tokio::process::Command::new("bash")
        .arg("-lc")
        .arg(INSTALLER)
        .stdin(Stdio::null())
        .output();
    let output = match tokio::time::timeout(UPDATE_TIMEOUT, run).await {
        Err(_) => return Err("Update failed: the installer timed out.".to_owned()),
        Ok(Err(error)) => return Err(format!("Update failed to start: {error}")),
        Ok(Ok(output)) => output,
    };
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let detail = tail(&stderr).or_else(|| tail(&stdout)).unwrap_or_default();
    Err(format!(
        "Update failed ({}).{}{detail}",
        output.status,
        if detail.is_empty() { "" } else { " " }
    ))
}

/// The last few lines of a command's output, for one transcript row.
fn tail(text: &str) -> Option<String> {
    let lines: Vec<&str> = text
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect();
    if lines.is_empty() {
        return None;
    }
    let start = lines.len().saturating_sub(OUTPUT_TAIL_LINES);
    Some(lines[start..].join(" / "))
}
