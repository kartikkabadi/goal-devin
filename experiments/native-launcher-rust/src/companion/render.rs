use super::model::{CompanionState, RunState};
use super::style::Theme;
use ratatui::layout::{Constraint, Direction, Layout, Margin, Rect};
use ratatui::style::Style;
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, Paragraph};
use ratatui::Frame;

pub struct RenderContext<'a> {
    pub state: &'a CompanionState,
    pub theme: &'a Theme,
    pub warning_scroll: usize,
    pub show_help: bool,
}

pub fn render(frame: &mut Frame, ctx: &RenderContext) {
    let area = frame.size();

    if area.width < 40 || area.height < 10 {
        let text = Text::from(vec![
            Line::from("Goal Devin companion"),
            Line::from("Terminal too small"),
        ]);
        let paragraph = Paragraph::new(text).style(ctx.theme.secondary());
        frame.render_widget(paragraph, area);
        return;
    }

    let main = Block::default()
        .title("Goal Devin")
        .borders(Borders::ALL)
        .border_style(ctx.theme.border_style(true))
        .border_set(ctx.theme.border_set());

    let inner = area.inner(Margin {
        horizontal: 1,
        vertical: 1,
    });
    frame.render_widget(main, area);

    let sections = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // header
            Constraint::Length(5), // session
            Constraint::Length(5), // worker
            Constraint::Length(4), // observation
            Constraint::Length(7), // lifecycle
            Constraint::Min(4),    // warnings / help
        ])
        .split(inner);

    render_header(frame, ctx, sections[0]);
    render_session(frame, ctx, sections[1]);
    render_worker(frame, ctx, sections[2]);
    render_observation(frame, ctx, sections[3]);
    render_lifecycle(frame, ctx, sections[4]);

    if ctx.show_help {
        let block = Block::default()
            .title("Help")
            .borders(Borders::ALL)
            .border_style(ctx.theme.border_style(true))
            .border_set(ctx.theme.border_set());
        let help = Paragraph::new(help_text(ctx.theme))
            .block(block)
            .style(ctx.theme.primary());
        frame.render_widget(Clear, sections[5]);
        frame.render_widget(help, sections[5]);
    } else {
        render_warnings(frame, ctx, sections[5]);
    }
}

fn render_header(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let status = ctx.state.run_state.label();
    let color = ctx.theme.state_color(&ctx.state.run_state);
    let elapsed = ctx.state.elapsed_since_start();
    let line = Line::from(vec![
        Span::styled("Goal Devin  ", ctx.theme.heading()),
        Span::styled(status, Style::default().fg(color)),
        Span::raw("  "),
        Span::styled(elapsed, ctx.theme.dim()),
    ]);
    frame.render_widget(Paragraph::new(line), area);
}

fn render_session(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let block = section_block(ctx.theme, "Session");
    let lines = vec![
        key_value(ctx.theme, "State", ctx.state.run_state.label()),
        key_value(ctx.theme, "Elapsed", ctx.state.elapsed_since_start()),
        key_value(ctx.theme, "Model", ctx.state.model.as_str()),
        key_value(ctx.theme, "Permission", ctx.state.permission_mode.as_str()),
    ];
    let text = Text::from(lines);
    frame.render_widget(
        Paragraph::new(text).block(block).style(ctx.theme.primary()),
        area,
    );
}

fn render_worker(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let block = section_block(ctx.theme, "Worker");
    let policy = if ctx.state.profile_id.is_empty() {
        "—"
    } else {
        "read-only"
    };
    let lines = vec![
        key_value(ctx.theme, "Profile", ctx.state.short_profile_id()),
        key_value(ctx.theme, "Policy", policy),
        key_value(ctx.theme, "Configured model", ctx.state.model.as_str()),
    ];
    frame.render_widget(
        Paragraph::new(Text::from(lines))
            .block(block)
            .style(ctx.theme.primary()),
        area,
    );
}

fn render_observation(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let block = section_block(ctx.theme, "Observation");
    let health = if ctx.state.sidecar_healthy {
        ("healthy", ctx.theme.success())
    } else {
        ("waiting", ctx.theme.warning())
    };
    let lines = vec![
        Line::from(vec![
            Span::styled("Sidecar: ", ctx.theme.label()),
            Span::styled(health.0, health.1),
        ]),
        Line::from(vec![
            Span::styled("Events: ", ctx.theme.label()),
            Span::styled(ctx.state.event_count.to_string(), ctx.theme.accent()),
        ]),
        Line::from(vec![
            Span::styled("Latest: ", ctx.theme.label()),
            Span::styled(
                if ctx.state.last_event_type.is_empty() {
                    "—"
                } else {
                    &ctx.state.last_event_type
                },
                ctx.theme.secondary(),
            ),
        ]),
    ];
    frame.render_widget(
        Paragraph::new(Text::from(lines))
            .block(block)
            .style(ctx.theme.primary()),
        area,
    );
}

fn render_lifecycle(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let block = section_block(ctx.theme, "Lifecycle");
    let phases = [
        ("setup", RunState::PreparingRuntime),
        ("hook", RunState::InstallingHook),
        ("profile", RunState::CreatingProfile),
        ("sidecar", RunState::StartingSidecar),
        ("launch", RunState::LaunchingDevin),
        ("Devin", RunState::DevinActive),
        ("cleanup", RunState::CleaningUp),
    ];

    let current = ctx.state.lifecycle_phase.as_str();
    let mut lines: Vec<Line> = Vec::new();
    for (label, _marker) in phases {
        let active = label == current || matches_active(label, &ctx.state.run_state);
        let style = if active {
            ctx.theme.heading()
        } else {
            ctx.theme.dim()
        };
        let prefix = if active { "▸ " } else { "  " };
        lines.push(Line::from(Span::styled(
            format!("{}{}", prefix, label),
            style,
        )));
    }

    frame.render_widget(
        Paragraph::new(Text::from(lines))
            .block(block)
            .style(ctx.theme.primary()),
        area,
    );
}

fn render_warnings(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let block = section_block(ctx.theme, "Warnings");
    if ctx.state.warnings.is_empty() {
        let text = Text::from(Line::from(Span::styled("None", ctx.theme.dim())));
        frame.render_widget(
            Paragraph::new(text).block(block).style(ctx.theme.primary()),
            area,
        );
        return;
    }

    let start = ctx
        .warning_scroll
        .min(ctx.state.warnings.len().saturating_sub(1));
    let visible = (area.height as usize).saturating_sub(2).max(1);
    let end = (start + visible).min(ctx.state.warnings.len());
    let items: Vec<ListItem> = ctx.state.warnings[start..end]
        .iter()
        .map(|w| ListItem::new(Line::from(Span::styled(sanitize(w), ctx.theme.warning()))))
        .collect();
    let list = List::new(items).block(block).style(ctx.theme.primary());
    frame.render_widget(list, area);
}

fn help_text(theme: &Theme) -> Text {
    let lines = vec![
        Line::from(vec![
            Span::styled("q", theme.label()),
            Span::raw("  close/hide companion"),
        ]),
        Line::from(vec![
            Span::styled("?", theme.label()),
            Span::raw("  toggle this help"),
        ]),
        Line::from(vec![
            Span::styled("j / ↓", theme.label()),
            Span::raw(" scroll warnings down"),
        ]),
        Line::from(vec![
            Span::styled("k / ↑", theme.label()),
            Span::raw(" scroll warnings up"),
        ]),
        Line::from(vec![
            Span::styled("Ctrl+c", theme.label()),
            Span::raw(" exit"),
        ]),
    ];
    Text::from(lines)
}

fn section_block<'a>(theme: &'a Theme, title: &'a str) -> Block<'a> {
    Block::default()
        .title(title)
        .borders(Borders::ALL)
        .border_style(theme.border_style(false))
        .border_set(theme.border_set())
}

fn key_value<'a>(
    theme: &'a Theme,
    key: &'a str,
    value: impl Into<std::borrow::Cow<'a, str>> + std::convert::AsRef<str>,
) -> Line<'a> {
    Line::from(vec![
        Span::styled(format!("{}: ", key), theme.label()),
        Span::styled(sanitize(value), theme.secondary()),
    ])
}

fn matches_active(label: &str, run_state: &RunState) -> bool {
    matches!(
        (label, run_state),
        ("setup", RunState::Initializing)
            | ("setup", RunState::PreparingRuntime)
            | ("hook", RunState::InstallingHook)
            | ("profile", RunState::CreatingProfile)
            | ("sidecar", RunState::StartingSidecar)
            | ("launch", RunState::LaunchingDevin)
            | ("Devin", RunState::DevinActive)
            | ("cleanup", RunState::CleaningUp)
            | ("cleanup", RunState::Complete)
            | ("cleanup", RunState::Failed)
    )
}

fn sanitize(input: impl AsRef<str>) -> String {
    input
        .as_ref()
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    fn make_state() -> CompanionState {
        let mut state = CompanionState::new();
        state.run_state = RunState::DevinActive;
        state.model = "glm-5.2".to_string();
        state.permission_mode = "accept-edits".to_string();
        state.profile_id = "goal-devin-worker-abc123".to_string();
        state.sidecar_healthy = true;
        state.event_count = 3;
        state.last_event_type = "run_subagent".to_string();
        state.lifecycle_phase = "Devin".to_string();
        state.started_at = Some(chrono::Utc::now());
        state.updated_at = Some(chrono::Utc::now());
        state
    }

    #[test]
    fn render_does_not_panic_on_normal_size() {
        let backend = TestBackend::new(120, 40);
        let mut terminal = Terminal::new(backend).unwrap();
        let state = make_state();
        let theme = Theme::from_env(false, false);
        let ctx = RenderContext {
            state: &state,
            theme: &theme,
            warning_scroll: 0,
            show_help: false,
        };
        terminal.draw(|f| render(f, &ctx)).unwrap();
    }

    #[test]
    fn render_does_not_panic_on_small_size() {
        let backend = TestBackend::new(30, 8);
        let mut terminal = Terminal::new(backend).unwrap();
        let state = make_state();
        let theme = Theme::from_env(false, false);
        let ctx = RenderContext {
            state: &state,
            theme: &theme,
            warning_scroll: 0,
            show_help: false,
        };
        terminal.draw(|f| render(f, &ctx)).unwrap();
    }

    #[test]
    fn render_ascii_and_no_color_does_not_panic() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let state = make_state();
        let theme = Theme::from_env(true, true);
        let ctx = RenderContext {
            state: &state,
            theme: &theme,
            warning_scroll: 0,
            show_help: false,
        };
        terminal.draw(|f| render(f, &ctx)).unwrap();
    }

    #[test]
    fn render_help_overlay_does_not_panic() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).unwrap();
        let mut state = make_state();
        state.warnings = vec!["warning one".to_string(), "warning two".to_string()];
        let theme = Theme::from_env(false, false);
        let ctx = RenderContext {
            state: &state,
            theme: &theme,
            warning_scroll: 1,
            show_help: true,
        };
        terminal.draw(|f| render(f, &ctx)).unwrap();
    }
}
