use super::model::CompanionState;
use super::render::{render, RenderContext};
use super::style::Theme;
use super::transport::Transport;
use anyhow::{Context, Result};
use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use crossterm::{cursor, QueueableCommand};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use std::io::{self, stdout, Write};
use std::path::Path;
use std::time::{Duration, Instant};

pub struct App {
    transport: Transport,
    state: CompanionState,
    theme: Theme,
    warning_scroll: usize,
    show_help: bool,
    last_poll: Instant,
    poll_interval: Duration,
    needs_draw: bool,
}

impl App {
    pub fn new(runtime_dir: &Path, no_color: bool, ascii: bool, poll_ms: u64) -> Self {
        let theme = Theme::from_env(no_color, ascii);
        let transport = Transport::new(runtime_dir);
        Self {
            transport,
            state: CompanionState::new(),
            theme,
            warning_scroll: 0,
            show_help: false,
            last_poll: Instant::now(),
            poll_interval: Duration::from_millis(poll_ms),
            needs_draw: true,
        }
    }

    pub fn run(&mut self) -> Result<i32> {
        setup_terminal()?;
        let mut terminal = Terminal::new(CrosstermBackend::new(io::stdout()))
            .context("failed to create terminal")?;

        let result = self.event_loop(&mut terminal);

        restore_terminal()?;

        match result {
            Ok(code) => Ok(code),
            Err(e) => {
                eprintln!("goal-devin-companion: {}", e);
                Ok(1)
            }
        }
    }

    fn event_loop<B: ratatui::backend::Backend>(
        &mut self,
        terminal: &mut Terminal<B>,
    ) -> Result<i32> {
        let mut last_state_change = Instant::now();

        loop {
            if self.last_poll.elapsed() >= self.poll_interval {
                self.last_poll = Instant::now();
                if let Some(new_state) = self.transport.read()? {
                    if new_state.updated_at != self.state.updated_at {
                        self.state = new_state;
                        self.needs_draw = true;
                        last_state_change = Instant::now();
                    }
                }
            }

            if self.needs_draw || last_state_change.elapsed() < Duration::from_millis(500) {
                terminal.draw(|f| {
                    let ctx = RenderContext {
                        state: &self.state,
                        theme: &self.theme,
                        warning_scroll: self.warning_scroll,
                        show_help: self.show_help,
                    };
                    render(f, &ctx);
                })?;
                self.needs_draw = false;
                last_state_change = Instant::now();
            }

            if event::poll(Duration::from_millis(50))? {
                match event::read()? {
                    Event::Key(key) if key.kind == KeyEventKind::Press => {
                        if key.code == KeyCode::Char('q') || key.code == KeyCode::Esc {
                            return Ok(0);
                        }
                        if key.modifiers == KeyModifiers::CONTROL && key.code == KeyCode::Char('c')
                        {
                            return Ok(0);
                        }
                        self.handle_key(key);
                        self.needs_draw = true;
                    }
                    Event::Resize(_, _) => {
                        self.needs_draw = true;
                    }
                    Event::FocusGained | Event::FocusLost => {
                        self.needs_draw = true;
                    }
                    _ => {}
                }
            }

            // If the session finished and we have not seen a state update in a while,
            // draw at least once per second so the elapsed clock ticks.
            if last_state_change.elapsed() > Duration::from_secs(1) {
                self.needs_draw = true;
            }
        }
    }

    fn handle_key(&mut self, key: event::KeyEvent) {
        match key.code {
            KeyCode::Char('?') => self.show_help = !self.show_help,
            KeyCode::Char('j') | KeyCode::Down => {
                let max = self.state.warnings.len().saturating_sub(1);
                self.warning_scroll = (self.warning_scroll + 1).min(max);
            }
            KeyCode::Char('k') | KeyCode::Up => {
                self.warning_scroll = self.warning_scroll.saturating_sub(1);
            }
            KeyCode::Char('g') => self.warning_scroll = 0,
            KeyCode::Char('G') => {
                let max = self.state.warnings.len().saturating_sub(1);
                self.warning_scroll = max;
            }
            _ => {}
        }
    }
}

fn setup_terminal() -> Result<()> {
    enable_raw_mode()?;
    let mut stdout = stdout();
    stdout
        .queue(EnterAlternateScreen)?
        .queue(cursor::Hide)?
        .flush()?;
    Ok(())
}

fn restore_terminal() -> Result<()> {
    disable_raw_mode()?;
    let mut stdout = stdout();
    stdout
        .queue(LeaveAlternateScreen)?
        .queue(cursor::Show)?
        .flush()?;
    Ok(())
}
