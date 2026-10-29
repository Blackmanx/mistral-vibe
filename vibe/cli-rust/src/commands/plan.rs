//! `/plan`: plan-first turn that ends with a TODO list and no edits.

use std::sync::Arc;

use crate::app::App;
use crate::server::Client;
use crate::{message_queue, ui};

pub fn run(app: &mut App, client: &Arc<Client>, value: &str) {
    let task = value
        .split_once(char::is_whitespace)
        .map(|(_, rest)| rest.trim())
        .unwrap_or_default();
    if task.is_empty() {
        ui::notice::show(
            app,
            "Usage: `/plan <task>` — inspect first, then produce a plan and TODO list.",
            4,
        );
        return;
    }
    let prompt = format!(
        "PLAN MODE. Do not edit files, run state-changing commands, or install anything until the user approves.\n\n\
         1. Inspect only the code and constraints needed to decide the approach.\n\
         2. Write a concise, decision-complete plan: context, exact files and symbols, execution order, risks, and verification commands.\n\
         3. Create the execution checklist with the `todo` tool: one item per meaningful step, the first item `in_progress`. In the same response as your next tool call, never as a standalone turn.\n\
         4. Stop and wait for approval. Do not start implementing.\n\n\
         Task: {task}"
    );
    ui::notice::show(app, "Planning first; no files will be changed.", 3);
    message_queue::enqueue_prompt(app, client, prompt);
    message_queue::resume(app, client);
}
