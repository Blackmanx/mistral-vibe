//! `/btw`: ephemeral side question answered from the current transcript.

use std::sync::Arc;

use serde_json::json;

use super::event::{dispatch, CommandEvent};
use crate::app::App;
use crate::server::{method, Client};

pub fn run(app: &mut App, client: &Arc<Client>, value: &str) {
    let question = value
        .split_once(char::is_whitespace)
        .map(|(_, rest)| rest.trim())
        .unwrap_or_default();
    if question.is_empty() {
        crate::ui::notice::show(
            app,
            "Usage: `/btw <question>` — answers from this conversation without adding to it.",
            4,
        );
        return;
    }
    let images = app.chat_input.pasted_images.attach(value, Vec::new());
    let Some((session_id, tx)) = dispatch(app) else {
        return;
    };
    let params = json!({"sessionId": session_id, "question": question, "images": images});
    let client = client.clone();
    tokio::spawn(async move {
        let event = match client.request(method::SESSION_BTW, params).await {
            Ok(value) => {
                let answer = value
                    .get("answer")
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or_default()
                    .trim();
                if answer.is_empty() {
                    CommandEvent::Error("The side question returned no answer.".to_owned())
                } else {
                    CommandEvent::Result(format!(
                        "## /btw\n\n{answer}\n\n_Side question; not added to the conversation._"
                    ))
                }
            }
            Err(error) => CommandEvent::Error(format!("Side question failed: {error}")),
        };
        let _ = tx.try_send(event);
    });
}
