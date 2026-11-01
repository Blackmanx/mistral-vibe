//! `/memory`: show what the project remembers across sessions, and its rules.

use std::sync::Arc;

use serde_json::{json, Value};

use super::event::{dispatch, CommandEvent};
use crate::app::App;
use crate::server::{method, Client};

pub fn run(app: &mut App, client: &Arc<Client>, _value: &str) {
    let Some((session_id, tx)) = dispatch(app) else {
        return;
    };
    let client = client.clone();
    tokio::spawn(async move {
        let event = match execute(&client, &session_id).await {
            Ok(text) => CommandEvent::Result(text),
            Err(error) => CommandEvent::Error(format!("Memory request failed: {error}")),
        };
        let _ = tx.try_send(event);
    });
}

async fn execute(client: &Arc<Client>, session_id: &str) -> anyhow::Result<String> {
    let value: Value = client
        .request(
            method::SESSION_MEMORY_READ,
            json!({ "sessionId": session_id }),
        )
        .await?;
    Ok(value
        .get("text")
        .and_then(Value::as_str)
        .unwrap_or("The project memory could not be read.")
        .to_owned())
}
