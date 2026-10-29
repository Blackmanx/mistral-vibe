//! One compact row naming the images staged in the composer.

use ratatui::layout::Rect;
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Frame;

use crate::app::App;
use crate::ui::theme;

pub fn height(app: &App) -> u16 {
    let count = app
        .chat_input
        .pasted_images
        .referenced_len(&app.chat_input.input);
    u16::from(count > 0 || app.paste_image.in_flight > 0)
}

pub fn draw(app: &App, f: &mut Frame, area: Rect) {
    let count = app
        .chat_input
        .pasted_images
        .referenced_len(&app.chat_input.input);
    let reading = app.paste_image.in_flight > 0;
    if (count == 0 && !reading) || area.width == 0 {
        return;
    }
    let label = match (count, reading) {
        (0, true) => "🖼 Reading image…".to_owned(),
        (1, false) => "🖼 Image".to_owned(),
        (1, true) => "🖼 Image · reading another…".to_owned(),
        (n, false) => format!("🖼 {n} images"),
        (n, true) => format!("🖼 {n} images · reading another…"),
    };
    let hint = if reading || count > 0 {
        "  Alt+V adds another"
    } else {
        ""
    };
    let line = Line::from(vec![
        Span::styled(label, theme::text(theme::primary())),
        Span::styled(hint, theme::muted_style()),
    ]);
    f.render_widget(Paragraph::new(line), area);
}
