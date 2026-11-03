//! Embeds the release notes, `../whats_new/<version>.md`, newest first, and
//! stamps the build with the commit it was made from.
//!
//! The fork releases by merging upstream, so two builds can carry the same
//! `version` and still differ: the update check compares this stamp with the
//! fork's `main` instead of relying on a version bump.

use std::path::{Path, PathBuf};
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    embed_whats_new();
    stamp_commit();
}

fn embed_whats_new() {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR");
    let dir = Path::new(&manifest).join("../whats_new");
    println!("cargo:rerun-if-changed={}", dir.display());
    let mut entries: Vec<((u64, u64, u64), String, PathBuf)> = std::fs::read_dir(&dir)
        .unwrap_or_else(|err| panic!("cannot read {}: {err}", dir.display()))
        .map(|file| file.expect("whats_new directory entry").path())
        .filter(|path| !file_name(path).starts_with('.'))
        .map(|path| {
            let version = file_name(&path)
                .strip_suffix(".md")
                .unwrap_or_else(|| panic!("{} is not a <version>.md file", path.display()))
                .to_owned();
            (parse(&version, &path), version, path)
        })
        .collect();
    entries.sort_by_key(|entry| std::cmp::Reverse(entry.0));
    let rows: String = entries
        .iter()
        .map(|(_, version, path)| format!("    ({version:?}, include_str!({path:?})),\n"))
        .collect();
    let out = Path::new(&std::env::var("OUT_DIR").expect("OUT_DIR")).join("whats_new.rs");
    std::fs::write(out, format!("&[\n{rows}]\n")).expect("write whats_new.rs");
}

fn stamp_commit() {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").unwrap_or_default();
    let repo = Path::new(&manifest).join("../..");
    // A new commit moves HEAD or the branch the checkout is on.
    for changed in [".git/HEAD", ".git/refs/heads/main", ".git/refs/heads/master"] {
        println!("cargo:rerun-if-changed={}", repo.join(changed).display());
    }

    let commit = Command::new("git")
        .args(["-C", &manifest, "rev-parse", "--short=7", "HEAD"])
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_owned())
        .filter(|sha| !sha.is_empty());

    match commit {
        Some(sha) => println!("cargo:rustc-env=VIBE_BUILD_COMMIT={sha}"),
        // Not a checkout (a tarball build): no stamp, and the update check
        // falls back to comparing versions.
        None => println!("cargo:rustc-env=VIBE_BUILD_COMMIT="),
    }
}

fn file_name(path: &Path) -> &str {
    path.file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
}

/// A strict `X.Y.Z` release version, the only name a release-notes file may have.
fn parse(version: &str, path: &Path) -> (u64, u64, u64) {
    let parts: Vec<u64> = version
        .split('.')
        .map(|part| part.parse().ok())
        .collect::<Option<_>>()
        .unwrap_or_default();
    match parts[..] {
        [major, minor, patch] => (major, minor, patch),
        _ => panic!("{} is not named after an X.Y.Z version", path.display()),
    }
}
