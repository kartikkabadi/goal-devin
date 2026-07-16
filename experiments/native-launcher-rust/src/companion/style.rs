use ratatui::style::{Color, Modifier, Style};

#[derive(Clone, Copy, Debug)]
pub enum ColorCapability {
    NoColor,
    Basic,
    Two56,
    TrueColor,
}

#[derive(Clone, Debug)]
pub struct Theme {
    pub capability: ColorCapability,
    pub ascii_borders: bool,
    pub dark_background: bool,
}

impl Theme {
    pub fn from_env(no_color: bool, ascii: bool) -> Self {
        let capability;
        if no_color || std::env::var_os("NO_COLOR").is_some() {
            capability = ColorCapability::NoColor;
        } else if let Some(ct) = std::env::var_os("COLORTERM") {
            let s = ct.to_string_lossy().to_lowercase();
            if s.contains("truecolor") || s.contains("24bit") {
                capability = ColorCapability::TrueColor;
            } else if s.contains("256") {
                capability = ColorCapability::Two56;
            } else {
                capability = ColorCapability::Basic;
            }
        } else if let Some(term) = std::env::var_os("TERM") {
            let s = term.to_string_lossy().to_lowercase();
            if s.contains("truecolor") || s.contains("24bit") || s.contains("256color") {
                capability = ColorCapability::TrueColor;
            } else if s.contains("256") {
                capability = ColorCapability::Two56;
            } else if s.contains("color") {
                capability = ColorCapability::Basic;
            } else {
                capability = ColorCapability::NoColor;
            }
        } else {
            capability = ColorCapability::NoColor;
        }

        let dark_background = match std::env::var_os("COLORFGBG") {
            Some(v) => {
                let s = v.to_string_lossy();
                // Format is "fg;bg" or "fg:bg". A dark background is black (0).
                let bg = s.split([';', ':']).nth(1).unwrap_or("");
                bg == "0" || bg.starts_with('0')
            }
            None => true,
        };

        Self {
            capability,
            ascii_borders: ascii || std::env::var_os("GOAL_DEVIN_COMPANION_ASCII").is_some(),
            dark_background,
        }
    }

    pub fn text_primary(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic if self.dark_background => Color::White,
            ColorCapability::Basic => Color::Black,
            ColorCapability::Two56 | ColorCapability::TrueColor if self.dark_background => {
                Color::Rgb(0xE0, 0xE0, 0xE0)
            }
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0x20, 0x20, 0x20),
        }
    }

    pub fn text_secondary(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic if self.dark_background => Color::Gray,
            ColorCapability::Basic => Color::DarkGray,
            ColorCapability::Two56 | ColorCapability::TrueColor if self.dark_background => {
                Color::Rgb(0xA0, 0xA0, 0xA0)
            }
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0x60, 0x60, 0x60),
        }
    }

    pub fn text_dim(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic if self.dark_background => Color::DarkGray,
            ColorCapability::Basic => Color::Gray,
            ColorCapability::Two56 | ColorCapability::TrueColor if self.dark_background => {
                Color::Rgb(0x70, 0x70, 0x70)
            }
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0x90, 0x90, 0x90),
        }
    }

    pub fn accent_primary(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic if self.dark_background => Color::Cyan,
            ColorCapability::Basic => Color::Blue,
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0x4F, 0xC3, 0xF7),
        }
    }

    pub fn state_success(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic => Color::Green,
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0x4C, 0xC0, 0x88),
        }
    }

    pub fn state_warning(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic => Color::Yellow,
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0xF5, 0xC5, 0x4C),
        }
    }

    pub fn state_error(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic => Color::Red,
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0xFF, 0x6B, 0x6B),
        }
    }

    pub fn border_default(&self) -> Color {
        match self.capability {
            ColorCapability::NoColor => Color::Reset,
            ColorCapability::Basic if self.dark_background => Color::DarkGray,
            ColorCapability::Basic => Color::Gray,
            ColorCapability::Two56 | ColorCapability::TrueColor if self.dark_background => {
                Color::Rgb(0x44, 0x44, 0x44)
            }
            ColorCapability::Two56 | ColorCapability::TrueColor => Color::Rgb(0xCC, 0xCC, 0xCC),
        }
    }

    pub fn border_active(&self) -> Color {
        self.accent_primary()
    }

    pub fn selection(&self) -> Color {
        self.accent_primary()
    }

    pub fn spinner(&self) -> Color {
        self.accent_primary()
    }

    pub fn primary(&self) -> Style {
        Style::default().fg(self.text_primary())
    }

    pub fn secondary(&self) -> Style {
        Style::default().fg(self.text_secondary())
    }

    pub fn dim(&self) -> Style {
        Style::default().fg(self.text_dim())
    }

    pub fn accent(&self) -> Style {
        Style::default().fg(self.accent_primary())
    }

    pub fn success(&self) -> Style {
        Style::default().fg(self.state_success())
    }

    pub fn warning(&self) -> Style {
        Style::default().fg(self.state_warning())
    }

    pub fn error(&self) -> Style {
        Style::default().fg(self.state_error())
    }

    pub fn label(&self) -> Style {
        Style::default()
            .fg(self.text_dim())
            .add_modifier(Modifier::BOLD)
    }

    pub fn heading(&self) -> Style {
        Style::default()
            .fg(self.accent_primary())
            .add_modifier(Modifier::BOLD)
    }

    pub fn border_style(&self, active: bool) -> Style {
        Style::default().fg(if active {
            self.border_active()
        } else {
            self.border_default()
        })
    }

    pub fn border_set(&self) -> ratatui::symbols::border::Set {
        if self.ascii_borders {
            ratatui::symbols::border::Set {
                top_left: "+",
                top_right: "+",
                bottom_left: "+",
                bottom_right: "+",
                vertical_left: "|",
                vertical_right: "|",
                horizontal_top: "-",
                horizontal_bottom: "-",
            }
        } else {
            ratatui::symbols::border::PLAIN
        }
    }

    pub fn state_color(&self, state: &super::model::RunState) -> Color {
        use super::model::RunState;
        match state {
            RunState::Complete => self.state_success(),
            RunState::Failed | RunState::Warning => self.state_error(),
            RunState::DevinActive => self.state_success(),
            _ => self.accent_primary(),
        }
    }
}
