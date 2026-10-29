//! `/goal`: read, set, pause, resume, or clear the session goal.

use std::sync::Arc;

use serde_json::json;

use super::event::{dispatch, CommandEvent};
use crate::app::App;
use crate::server::{method, Client};

const HELP: &str = "## Goal\n\nUsage: `/goal` (status), `/goal set <objective>`, `/goal pause`, `/goal resume`, `/goal clear`";

pub fn run(app: &mut App, client: &Arc<Client>, value: &str) {
    let args = value
        .split_once(char::is_whitespace)
        .map(|(_, rest)| rest.trim())
        .unwrap_or_default();
    let (method_name, params, action) = match args {
        "" | "status" | "show" => (method::SESSION_GOAL_READ, json!({"sessionId": ""}), "read"),
        "pause" => (
            method::SESSION_GOAL_PAUSE,
            json!({"sessionId": ""}),
            "pause",
        ),
        "resume" => (
            method::SESSION_GOAL_RESUME,
            json!({"sessionId": ""}),
            "resume",
        ),
        "clear" => (
            method::SESSION_GOAL_CLEAR,
            json!({"sessionId": ""}),
            "clear",
        ),
        _ => {
            let Some(objective) = args.strip_prefix("set ") else {
                crate::ui::notice::show(app, HELP, 4);
                return;
            };
            if objective.trim().is_empty() {
                crate::ui::notice::show(app, "Usage: `/goal set <objective>`", 4);
                return;
            }
            (
                method::SESSION_GOAL_SET,
                json!({"sessionId": "", "objective": objective.trim()}),
                "set",
            )
        }
    };
    let Some((session_id, tx)) = dispatch(app) else {
        return;
    };
    let mut params = params;
    params["sessionId"] = json!(session_id);
    let client = client.clone();
    tokio::spawn(async move {
        let event = match client.request(method_name, params).await {
            Ok(value) => CommandEvent::Result(render(action, &value)),
            Err(error) => CommandEvent::Error(format!("Goal request failed: {error}")),
        };
        let _ = tx.try_send(event);
    });
}

fn render(action: &str, value: &serde_json::Value) -> String {
    if action == "clear" {
        return match value.get("cleared").and_then(serde_json::Value::as_bool) {
            Some(true) => "Goal cleared.".to_owned(),
            _ => "No goal to clear.".to_owned(),
        };
    }
    let Some(goal) = value.get("goal").filter(|goal| !goal.is_null()) else {
        return "No goal. Create one with `/goal set <objective>`.".to_owned();
    };
    let objective = goal
        .get("objective")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default();
    let status = goal
        .get("status")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("unknown");
    let used = goal
        .get("tokensUsed")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or_default();
    let budget = goal
        .get("tokenBudget")
        .and_then(serde_json::Value::as_u64)
        .map(|budget| format!("{used}/{budget}"))
        .unwrap_or_else(|| format!("{used}/unbounded"));
    format!(
        "## Goal\n\n- **Status**: {status}\n- **Objective**: {objective}\n- **Tokens**: {budget}\n\nUse `/goal pause`, `/goal resume`, or `/goal clear` to manage it."
    )
}
