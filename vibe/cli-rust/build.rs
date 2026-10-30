//! Stamp the build with the commit it was made from.
//!
//! The fork releases by merging upstream, so two builds can carry the same
//! `version` and still differ: the update check compares this stamp with the
//! fork's `main` instead of relying on a version bump.

use std::path::Path;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
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
