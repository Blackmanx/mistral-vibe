//! The version this build reports, carrying the source it was built from.

/// The package version alone, as the release declares it.
pub const PACKAGE: &str = env!("CARGO_PKG_VERSION");

/// The commit this build came from, when it was built from a checkout.
pub const COMMIT: &str = match option_env!("VIBE_BUILD_COMMIT") {
    Some(commit) => commit,
    None => "",
};

/// The version with its fork stamp: `3.0.4+fork.a1b2c3d`.
///
/// The local segment names the source and the exact commit, so two builds of
/// the same release are told apart and the update check can compare commits
/// instead of waiting for a version bump. A build without a checkout keeps the
/// bare release.
pub fn current() -> String {
    if COMMIT.is_empty() {
        PACKAGE.to_owned()
    } else {
        format!("{PACKAGE}+fork.{COMMIT}")
    }
}

/// The fork commit a version string carries, if it carries one.
pub fn fork_commit(version: &str) -> Option<&str> {
    version
        .split_once("+fork.")
        .map(|(_, commit)| commit)
        .filter(|commit| !commit.is_empty())
}
