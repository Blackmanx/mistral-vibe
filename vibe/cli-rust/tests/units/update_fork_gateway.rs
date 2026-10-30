//! The fork's update answer: the version its `main` manifest declares.

use vibe_rs::commands::has_command;
use vibe_rs::update_notifier::gateway::parse_pyproject_version;

#[test]
fn reads_the_version_of_the_project_table() {
    let manifest = r#"[build-system]
requires = ["maturin"]

[project]
name = "mistral-vibe"
version = "3.1.0"
description = "Minimal CLI coding agent by Mistral"
"#;
    assert_eq!(parse_pyproject_version(manifest).as_deref(), Some("3.1.0"));
}

#[test]
fn ignores_a_version_outside_the_project_table() {
    let manifest = r#"[tool.other]
version = "9.9.9"

[project]
name = "mistral-vibe"

[tool.package]
version = "8.8.8"
"#;
    assert_eq!(parse_pyproject_version(manifest), None);
}

#[test]
fn ignores_a_manifest_without_a_project_table() {
    assert_eq!(parse_pyproject_version("[tool.x]\nname = \"y\"\n"), None);
}

#[test]
fn update_is_a_builtin_command() {
    assert!(has_command("/update"));
}
