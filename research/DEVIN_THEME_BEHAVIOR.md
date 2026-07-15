# Devin CLI — Theme Behavior

## Observed color/theme system

The binary contains HTML/CSS theme strings suggesting a design-token approach:

| Token | Role |
|-------|------|
| `--surface-base` | Background (transparent in terminal) |
| `--surface-elevated` | Elevated panels |
| `--surface-overlay` | Overlays/modals |
| `--surface-accent` | Accent background |
| `--text-primary` | Main text |
| `--text-muted` | Secondary text |
| `--text-warning` | Warning text |
| `--border-default` | Borders |

Example literal values found:

```css
--surface-base: transparent;
--surface-elevated: #1f1f1f;   /* dark */
--surface-elevated: #eeeeee;   /* light */
--surface-overlay: #002b36;    /* dark */
--surface-overlay: #e8e8e8;    /* light */
--surface-accent: #0d1f2d;     /* dark */
--surface-accent: #e0f0fa;     /* light */
```

## Semantic color roles

Strings indicate the following semantic roles are used internally:

```
primary
muted
success
warning
error
accent
border
selected
thinking
tool
permission
```

These map naturally to the planned Goal Devin `ultra` dashboard renderer.

## Modes

Observed strings:

- `light`
- `terminal dark`
- `terminal light`
- `select`

This implies at least light, dark, and terminal-adaptive modes, plus a selection highlight state.

## `NO_COLOR` test

`NO_COLOR=1 devin` in a pseudo-TTY did **not** suppress the bold `Welcome to Devin CLI!` ANSI sequence (`ESC[1m...ESC[0m`). The startup banner may be hardcoded or `NO_COLOR` is only honored after the UI framework initializes. More testing is needed.

## Recommendation for Goal Devin

Adopt the same token names where practical, but do not copy proprietary visuals. A minimal `ultra` theme should support:

- `NO_COLOR` / `CLICOLOR=0` fully disables ANSI.
- `--theme dark|light|terminal`.
- Semantic tokens: `primary`, `muted`, `success`, `warning`, `error`, `accent`, `border`, `selected`, `thinking`, `tool`, `permission`.
- `terminal` mode reads the terminal's actual background and selects dark/light automatically.

## Untested

- 16-color terminal fallback.
- 256-color terminal.
- Truecolor detection.
- Redirected output with `NO_COLOR`.
- Theme switching at runtime.
