//! The home-directory guard: standing in `~` starts Vibe in the temp directory.

use std::path::Path;

use clap::Parser;
use vibe_rs::cli::{home_fallback, Cli};

#[test]
fn the_home_directory_falls_back_to_the_temporary_directory() {
    let home = Path::new("/home/someone");
    assert_eq!(
        home_fallback(Some(home), Some(home)),
        Some(std::env::temp_dir())
    );
}

#[test]
fn another_directory_is_kept() {
    let home = Path::new("/home/someone");
    assert_eq!(
        home_fallback(Some(Path::new("/tmp/work")), Some(home)),
        None
    );
}

#[test]
fn without_a_known_home_nothing_moves() {
    assert_eq!(home_fallback(Some(Path::new("/home/someone")), None), None);
}

#[test]
fn allow_home_is_a_flag() {
    let plain = Cli::try_parse_from(["vibe"]).expect("parse");
    assert!(!plain.allow_home);
    let allowed = Cli::try_parse_from(["vibe", "--allow-home"]).expect("parse");
    assert!(allowed.allow_home);
}
