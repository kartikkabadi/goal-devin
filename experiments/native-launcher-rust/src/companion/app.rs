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
use std::io::{self, stdout, Stdout, Write};
use std::path::Path;
use std::sync::{Arc, Mutex};
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
        let _panic_guard = PanicHookGuard::install();
        let _guard = TerminalGuard::setup()?;
        let mut terminal = Terminal::new(CrosstermBackend::new(io::stdout()))
            .context("failed to create terminal")?;

        let result = self.event_loop(&mut terminal);

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

struct TerminalGuard {
    raw_mode: bool,
    alternate_screen: bool,
    cursor_hidden: bool,
}

impl TerminalGuard {
    fn setup() -> Result<Self> {
        enable_raw_mode()?;
        let mut guard = Self {
            raw_mode: true,
            alternate_screen: false,
            cursor_hidden: false,
        };
        let mut stdout = stdout();

        if let Err(e) = stdout.queue(EnterAlternateScreen) {
            drop(guard);
            return Err(e.into());
        }
        guard.alternate_screen = true;

        if let Err(e) = stdout.queue(cursor::Hide) {
            drop(guard);
            return Err(e.into());
        }
        guard.cursor_hidden = true;

        if let Err(e) = stdout.flush() {
            drop(guard);
            return Err(e.into());
        }

        Ok(guard)
    }

    fn restore(&mut self) {
        let mut stdout = StdoutWrapper(stdout());
        if self.cursor_hidden {
            let _ = stdout.queue(cursor::Show);
        }
        if self.alternate_screen {
            let _ = stdout.queue(LeaveAlternateScreen);
        }
        if self.raw_mode {
            let _ = disable_raw_mode();
        }
        let _ = stdout.flush();
    }
}

impl Drop for TerminalGuard {
    fn drop(&mut self) {
        self.restore();
    }
}

/// Newtype so we can call `QueueableCommand` methods on `Stdout` without
/// importing the trait at call sites.
struct StdoutWrapper(Stdout);

impl std::ops::DerefMut for StdoutWrapper {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl std::ops::Deref for StdoutWrapper {
    type Target = Stdout;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

type PanicHook = Box<dyn Fn(&std::panic::PanicHookInfo<'_>) + Sync + Send + 'static>;

struct PanicHookGuard {
    prev: Arc<Mutex<Option<PanicHook>>>,
}

impl PanicHookGuard {
    fn install() -> Self {
        let prev = Arc::new(Mutex::new(Some(std::panic::take_hook())));
        let prev2 = Arc::clone(&prev);
        std::panic::set_hook(Box::new(move |info| {
            // Best-effort terminal restoration even if the panic happened
            // inside the rendering or event loop.
            let _ = disable_raw_mode();
            let mut stdout = stdout();
            let _ = stdout.queue(cursor::Show);
            let _ = stdout.queue(LeaveAlternateScreen);
            let _ = stdout.flush();
            if let Some(ref hook) = *prev2.lock().unwrap() {
                hook(info);
            }
        }));
        Self { prev }
    }
}

impl Drop for PanicHookGuard {
    fn drop(&mut self) {
        if let Some(prev) = self.prev.lock().unwrap().take() {
            std::panic::set_hook(prev);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_guard_setup_and_drop_is_safe() {
        // In a TTY this enters/exits raw + alternate screen via Drop;
        // in a non-TTY setup returns Err and nothing is left enabled.
        let guard = TerminalGuard::setup();
        drop(guard);
    }

    #[test]
    fn panic_hook_guard_installs_and_restores() {
        let original = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        {
            let _guard = PanicHookGuard::install();
        }
        let restored = std::panic::take_hook();
        drop(restored);
        std::panic::set_hook(original);
    }
}
