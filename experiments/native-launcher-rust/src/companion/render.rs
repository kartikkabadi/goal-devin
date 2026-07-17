use super::model::{CompanionState, RunState};
use super::style::Theme;
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::Paragraph;
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

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // header
            Constraint::Min(0),    // body
            Constraint::Length(1), // footer
        ])
        .split(area);

    render_header(frame, ctx, chunks[0]);
    render_body(frame, ctx, chunks[1]);
    render_footer(frame, ctx, chunks[2]);
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

fn render_body(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let sections = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(4), // session
            Constraint::Length(3), // observation
            Constraint::Length(8), // lifecycle
            Constraint::Min(1),    // warnings / help
        ])
        .split(area);

    render_session(frame, ctx, sections[0]);
    render_observation(frame, ctx, sections[1]);
    render_lifecycle(frame, ctx, sections[2]);

    if ctx.show_help {
        render_help(frame, ctx, sections[3]);
    } else {
        render_warnings(frame, ctx, sections[3]);
    }
}

fn render_session(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let policy = if ctx.state.profile_id.is_empty() {
        "—"
    } else {
        "read-only"
    };
    let text = Text::from(vec![
        section_title(ctx.theme, "Session"),
        Line::from(vec![
            key(ctx.theme, "Model: "),
            value(ctx.theme, ctx.state.model.as_str()),
            Span::raw("   "),
            key(ctx.theme, "Permission: "),
            value(ctx.theme, ctx.state.permission_mode.as_str()),
        ]),
        Line::from(vec![
            key(ctx.theme, "Profile: "),
            value(ctx.theme, ctx.state.short_profile_id()),
            Span::raw("   "),
            key(ctx.theme, "Policy: "),
            value(ctx.theme, policy),
        ]),
    ]);
    frame.render_widget(Paragraph::new(text).style(ctx.theme.primary()), area);
}

fn render_observation(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let health = if ctx.state.sidecar_healthy {
        ("healthy", ctx.theme.success())
    } else {
        ("waiting", ctx.theme.warning())
    };
    let latest = if ctx.state.last_event_type.is_empty() {
        "—".to_string()
    } else {
        sanitize(&ctx.state.last_event_type)
    };
    let text = Text::from(vec![
        section_title(ctx.theme, "Observation"),
        Line::from(vec![
            key(ctx.theme, "Sidecar: "),
            Span::styled(health.0, health.1),
            Span::raw("   "),
            key(ctx.theme, "Events: "),
            Span::styled(ctx.state.event_count.to_string(), ctx.theme.accent()),
            Span::raw("   "),
            key(ctx.theme, "Latest: "),
            value(ctx.theme, latest.as_str()),
        ]),
    ]);
    frame.render_widget(Paragraph::new(text).style(ctx.theme.primary()), area);
}

fn render_lifecycle(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
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
    let mut lines: Vec<Line> = vec![section_title(ctx.theme, "Lifecycle")];
    let mut phase_spans: Vec<Span> = Vec::new();
    for (i, (label, _marker)) in phases.iter().enumerate() {
        let active = *label == current || matches_active(label, &ctx.state.run_state);
        let style = if active {
            ctx.theme.heading()
        } else {
            ctx.theme.dim()
        };
        phase_spans.push(Span::styled(sanitize(label), style));
        if i < phases.len() - 1 {
            phase_spans.push(Span::styled("  ›  ", ctx.theme.dim()));
        }
    }
    lines.push(Line::from(phase_spans));
    frame.render_widget(
        Paragraph::new(Text::from(lines)).style(ctx.theme.primary()),
        area,
    );
}

fn render_warnings(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let title = section_title(ctx.theme, "Warnings");
    if ctx.state.warnings.is_empty() {
        frame.render_widget(
            Paragraph::new(Text::from(vec![
                title,
                Line::from(Span::styled("None", ctx.theme.dim())),
            ])),
            area,
        );
        return;
    }

    let start = ctx
        .warning_scroll
        .min(ctx.state.warnings.len().saturating_sub(1));
    let visible = area.height.saturating_sub(1).max(1) as usize;
    let end = (start + visible).min(ctx.state.warnings.len());
    let mut lines = vec![title];
    lines.extend(
        ctx.state.warnings[start..end]
            .iter()
            .map(|w| Line::from(Span::styled(sanitize(w), ctx.theme.warning()))),
    );
    frame.render_widget(
        Paragraph::new(Text::from(lines)).style(ctx.theme.primary()),
        area,
    );
}

fn render_help(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let text = Text::from(vec![
        section_title(ctx.theme, "Help"),
        Line::from(vec![
            key(ctx.theme, "q / Esc "),
            Span::raw("close/hide companion"),
        ]),
        Line::from(vec![key(ctx.theme, "? "), Span::raw("toggle this help")]),
        Line::from(vec![
            key(ctx.theme, "j / ↓ "),
            Span::raw("scroll warnings down"),
        ]),
        Line::from(vec![
            key(ctx.theme, "k / ↑ "),
            Span::raw("scroll warnings up"),
        ]),
        Line::from(vec![key(ctx.theme, "Ctrl+c "), Span::raw("exit")]),
    ]);
    frame.render_widget(Paragraph::new(text).style(ctx.theme.primary()), area);
}

fn render_footer(frame: &mut Frame, ctx: &RenderContext, area: Rect) {
    let left = ctx.state.run_state.label();
    let color = ctx.theme.state_color(&ctx.state.run_state);
    let sidecar = if ctx.state.sidecar_healthy {
        "up"
    } else {
        "down"
    };

    let right = format!(
        "{}  |  {}  |  events {}  |  sidecar {}",
        sanitize(ctx.state.model.as_str()),
        sanitize(ctx.state.permission_mode.as_str()),
        ctx.state.event_count,
        sidecar,
    );

    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(40), Constraint::Percentage(60)])
        .split(area);

    frame.render_widget(
        Paragraph::new(Line::from(Span::styled(
            left,
            Style::default().fg(color).add_modifier(Modifier::BOLD),
        ))),
        chunks[0],
    );
    frame.render_widget(
        Paragraph::new(Line::from(Span::styled(right, ctx.theme.dim()))),
        chunks[1],
    );
}

fn section_title<'a>(theme: &'a Theme, title: &'a str) -> Line<'a> {
    Line::from(vec![
        Span::styled(sanitize(title), theme.heading()),
        Span::raw(" "),
    ])
}

fn key<'a>(theme: &'a Theme, label: &'a str) -> Span<'a> {
    Span::styled(label, theme.label())
}

fn value<'a>(theme: &'a Theme, text: impl AsRef<str> + 'a) -> Span<'a> {
    Span::styled(sanitize(text), theme.secondary())
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
