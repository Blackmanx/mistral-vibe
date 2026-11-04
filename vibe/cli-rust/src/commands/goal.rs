//! `/goal`: pursue a persistent objective until it completes or is stopped.

use std::sync::Arc;

use anyhow::Result;
use serde_json::{json, Value};

use super::event::{dispatch, CommandEvent};
use crate::app::App;
use crate::server::{method, Client};

const HELP: &str = "## Goal\n\nUsage: `/goal <objective>` (start or replace), `/goal` (status, or resume when paused), `/goal stop`, `/goal status`, `/goal clear`";

/// What the user asked `/goal` to do, parsed from the text after the command.
enum GoalAction {
    /// Bare `/goal`: show the goal, and resume it when it is paused.
    ReadOrResume,
    Read,
    Pause,
    Resume,
    Clear,
    Set(String),
}

fn parse_goal_args(args: &str) -> Option<GoalAction> {
    match args {
        "" => Some(GoalAction::ReadOrResume),
        "status" | "show" => Some(GoalAction::Read),
        "stop" | "pause" => Some(GoalAction::Pause),
        "resume" => Some(GoalAction::Resume),
        "clear" | "drop" => Some(GoalAction::Clear),
        _ => {
            let objective = args
                .strip_prefix("set ")
                .map(str::trim)
                .unwrap_or_else(|| args.trim());
            if objective.is_empty() {
                None
            } else {
                Some(GoalAction::Set(objective.to_owned()))
            }
        }
    }
}

pub fn run(app: &mut App, client: &Arc<Client>, value: &str) {
    let args = value
        .split_once(char::is_whitespace)
        .map(|(_, rest)| rest.trim())
        .unwrap_or_default();
    let Some(action) = parse_goal_args(args) else {
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
            Err(error) => CommandEvent::Error(format!("Goal request failed: {error}")),
        };
        let _ = tx.try_send(event);
    });
}

async fn execute(client: &Arc<Client>, session_id: &str, action: GoalAction) -> Result<String> {
    match action {
        GoalAction::Read => {
            let value = client
                .request(
                    method::SESSION_GOAL_READ,
                    json!({ "sessionId": session_id }),
                )
                .await?;
            Ok(render_goal(&value))
        }
        GoalAction::ReadOrResume => {
            let value = client
                .request(
                    method::SESSION_GOAL_READ,
                    json!({ "sessionId": session_id }),
                )
                .await?;
            if goal_status(&value) == Some("paused") {
                let resumed = client
                    .request(
                        method::SESSION_GOAL_RESUME,
                        json!({ "sessionId": session_id }),
                    )
                    .await?;
                return Ok(format!("{}\n\nGoal resumed.", render_goal(&resumed)));
            }
            Ok(render_goal(&value))
        }
        GoalAction::Pause => {
            let value = client
                .request(
                    method::SESSION_GOAL_PAUSE,
                    json!({ "sessionId": session_id }),
                )
                .await?;
            Ok(match goal_status(&value) {
                Some("paused") => "Goal stopped. Use /goal to resume it.".to_owned(),
                _ => "No active goal to stop.".to_owned(),
            })
        }
        GoalAction::Resume => {
            let value = client
                .request(
                    method::SESSION_GOAL_RESUME,
                    json!({ "sessionId": session_id }),
                )
                .await?;
            Ok(match goal_status(&value) {
                Some("active") => "Goal resumed.".to_owned(),
                Some("paused") => "No paused goal to resume.".to_owned(),
                _ => "No goal. Start one with `/goal <objective>`.".to_owned(),
            })
        }
        GoalAction::Clear => {
            let value = client
                .request(
                    method::SESSION_GOAL_CLEAR,
                    json!({ "sessionId": session_id }),
                )
                .await?;
            Ok(match value.get("cleared").and_then(Value::as_bool) {
                Some(true) => "Goal cleared.".to_owned(),
                _ => "No goal to clear.".to_owned(),
            })
        }
        GoalAction::Set(objective) => {
            let value = client
                .request(
                    method::SESSION_GOAL_SET,
                    json!({ "sessionId": session_id, "objective": objective }),
                )
                .await?;
            Ok(format!(
                "Goal set. The agent pursues it until it completes, /goal stop, or you cancel a turn.\n\n{}",
                render_goal(&value)
            ))
        }
    }
}

fn goal_status(value: &Value) -> Option<&str> {
    value
        .get("goal")
        .filter(|goal| !goal.is_null())
        .and_then(|goal| goal.get("status"))
        .and_then(Value::as_str)
}

fn render_goal(value: &Value) -> String {
    let Some(goal) = value.get("goal").filter(|goal| !goal.is_null()) else {
        return "No goal. Start one with `/goal <objective>`.".to_owned();
    };
    let objective = goal
        .get("objective")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let status = goal
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let used = goal
        .get("tokensUsed")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let budget = goal
        .get("tokenBudget")
        .and_then(Value::as_u64)
        .map(|budget| format!("{used}/{budget}"))
        .unwrap_or_else(|| format!("{used}/unbounded"));
    format!(
        "## Goal\n\n- **Status**: {status}\n- **Objective**: {objective}\n- **Tokens**: {budget}\n\nUse `/goal stop`, `/goal`, or `/goal clear` to manage it."
    )
}
