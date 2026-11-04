//! `/advisor`: show, enable, or disable the advisor for this session.

use std::sync::Arc;

use serde_json::{json, Value};

use super::event::{dispatch, CommandEvent};
use crate::app::App;
use crate::server::{method, Client};

const HELP: &str = "## Advisor\n\nUsage: `/advisor` (state), `/advisor on`, `/advisor off`";

/// What the user asked `/advisor` to do.
enum AdvisorAction {
    /// Read the effective state.
    Read,
    /// Set the session-scoped override.
    Set(bool),
}

fn parse_advisor_args(args: &str) -> Option<AdvisorAction> {
    match args {
        "" | "status" | "show" => Some(AdvisorAction::Read),
        "on" | "enable" => Some(AdvisorAction::Set(true)),
        "off" | "disable" | "stop" => Some(AdvisorAction::Set(false)),
        _ => None,
    }
}

pub fn run(app: &mut App, client: &Arc<Client>, value: &str) {
    let args = value
        .split_once(char::is_whitespace)
        .map(|(_, rest)| rest.trim())
        .unwrap_or_default();
    let Some(action) = parse_advisor_args(args) else {
        crate::ui::notice::show(app, crate::app::Severity::Information, HELP, 4);
        return;
    };
    let Some((session_id, tx)) = dispatch(app) else {
        return;
    };
    let client = client.clone();
    crate::work::spawn(async move {
        let event = match execute(&client, &session_id, action).await {
            Ok(text) => CommandEvent::Result(text),
            Err(error) => CommandEvent::Error(format!("Advisor request failed: {error}")),
        };
        let _ = tx.try_send(event);
    });
}

async fn execute(
    client: &Arc<Client>,
    session_id: &str,
    action: AdvisorAction,
) -> anyhow::Result<String> {
    let params = match action {
        AdvisorAction::Read => json!({ "sessionId": session_id }),
        AdvisorAction::Set(enabled) => {
            json!({ "sessionId": session_id, "enabled": enabled })
        }
    };
    let value: Value = client
        .request(method::SESSION_ADVISOR_STATE, params)
        .await?;
    let enabled = value.get("enabled").and_then(Value::as_bool);
    let from_config = value.get("fromConfig").and_then(Value::as_bool);
    Ok(match (action, enabled) {
        (_, Some(true)) if from_config == Some(true) => {
            "Advisor on (from config). Use /advisor off for this session.".to_owned()
        }
        (_, Some(true)) => "Advisor on for this session.".to_owned(),
        (_, Some(false)) if from_config == Some(true) => {
            "Advisor off (from config). Use /advisor on for this session.".to_owned()
        }
        (_, Some(false)) => "Advisor off for this session.".to_owned(),
        _ => "The advisor state could not be read.".to_owned(),
    })
}
