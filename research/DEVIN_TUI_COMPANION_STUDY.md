# Devin TUI Companion Study

## Environment

* **Devin CLI version:** `devin 3000.1.27 (0d4bf12e)`
* **Installation source:** `https://cli.devin.ai/install.sh`
* **Installed binary path:** `/home/ubuntu/.local/bin/devin`
* **Operating system:** Linux `5.15.200` (x86_64)
* **Terminal emulator:** Konsole 21.12.3
* **Shell:** `/bin/bash`
* **Display:** `:0`
* **Inside tmux/screen:** No
* **Authentication:** API key (via `~/.local/share/devin/credentials.toml`)

### Konsole terminal environment during TUI observation

```text
TERM=xterm-256color
COLORTERM=truecolor
COLORFGBG=15;0
LANG=C.UTF-8
KONSOLE_VERSION=211203
KONSOLE_DBUS_SERVICE=:1.23
KONSOLE_DBUS_SESSION=/Sessions/1
KONSOLE_DBUS_WINDOW=/Windows/1
DISPLAY=:0
```

Sensitive environment values (API keys, tokens, session identifiers) were redacted from this document and from any screenshots committed to the repository.

## CLI surface

```text
$ devin --version
devin 3000.1.27 (0d4bf12e)
```

`devin --help` and `devin help` show the same content: a top-level usage block,
subcommands (`auth`, `mcp`, `rules`, `skills`, `plugins`, `cloud`, `list`,
`update`, `version`, `sandbox`, `setup`, `uninstall`, `acp`, `shell`, `help`),
and options (`--model`, `--permission-mode`, `--sandbox`, `-p/--print`,
`--export`, `-c/--continue`, `-r/--resume`, `--respect-workspace-trust`).

Key options for the Goal Devin launcher:

* `--model <MODEL>` — selects the root model.
* `--permission-mode <PERMISSION_MODE>` — one of `auto`, `accept-edits`, `smart`, `dangerous`.
* Positional prompt must be passed after `--`, e.g., `devin --model glm-5.2 --permission-mode auto -- hello`.

## Interactive TUI observations

The TUI was launched in a Konsole window with a dark background. The same
session was used for all screenshots.

### Trust prompt

On first run in a directory, Devin prints a trust prompt before entering the
main session:

```text
Do you trust the authors of this directory? For security, devin should not be run in directories with untrusted content.

1 Yes, trust ~/
2 No, exit
>
```

Observed traits:

* Dark background, light/white primary text.
* Numbered options (`1 Yes`, `2 No`).
* A single `>` input prompt.
* No heavy borders; the prompt is text-separated from the welcome text above.

### Active session layout

After selecting "Yes", the screen contains:

```text
Welcome to Devin CLI!
Logged in as <user>@<domain>.<tld>.
✓ Organization: <organization-name>
You're all set. Run devin to get started.
▲ Devin CLI works best when run in a project directory, not your home directory.

> hello

Pro - 90% remaining (resets in 2d 15h)

Hello! How can I help you today?

>
```

Followed by a bottom status bar:

```text
GLM-5.2 High                          Context: 12k / 200k tokens (6%)
```

Observed visual design:

* **Background:** very dark (appears near black).
* **Primary text:** light gray/white.
* **Dim/med text:** medium gray for secondary information.
* **Accent 1 (cyan/blue):** used for the ASCII "Devin CLI" logo header and model name.
* **Accent 2 (yellow-green):** used for the quota/progress bar (`Pro - 90% remaining...`).
* **Status colors:** green checkmark (`✓`) for healthy state, yellow triangle (`▲`) for mild warnings.
* **Density:** moderate; generous vertical spacing around the logo, compact lines for status and prompts.
* **Borders:** no boxed panels; sections are separated by blank lines and a single horizontal progress bar.
* **Input prompt:** `>` is minimal and left-aligned.
* **Status bar:** pinned to the bottom, two pieces of information left- and right-aligned.
* **No spinner:** in this short session no spinner/animation was visible.
* **Logo:** ASCII text art for "Devin CLI" plus version `v3000.1.27`.

### Second prompt state

After a second `> hello`, the screen is consistent with the first: welcome text,
logo, prompt, quota bar, assistant response, and the bottom status bar.

## Design tokens derived for the Goal Devin companion

Based on direct observation:

| Token | Derivation | Companion value |
|-------|------------|-----------------|
| Background | Konsole dark theme, Devin uses no background color | Do not set a hard background; inherit terminal. |
| `text.primary` | Light body text on dark | `#E0E0E0` / light gray. |
| `text.secondary` | Secondary labels, timestamps | `#A0A0A0` / medium gray. |
| `text.dim` | Muted metadata | `#707070` / dark gray. |
| `accent.primary` | Logo/cyan accent in terminal | `#4FC3F7` / light cyan. |
| `state.success` | Green checkmark | `#4CC088` / green. |
| `state.warning` | Yellow triangle, quota bar | `#F5C54C` / yellow. |
| `state.error` | Not observed directly; use a clear red | `#FF6B6B` / red. |
| `border.default` | No heavy borders; use subtle separators | `#444444` / dark gray. |
| `border.active` | Active section/header | `#4FC3F7` / accent cyan. |
| `spinner` | Same as accent | `#4FC3F7`. |

Copy style:

* Sentence case for labels, not ALL CAPS.
* Concise operational phrases: "Devin active", "Context: 12k / 200k tokens (6%)".
* Checkmark for healthy, triangle for warnings.
* No full sentences or conversational filler in status labels.

## Interaction observations

* The TUI consumes keyboard input directly; no evidence of mouse usage.
* `q` is not a Devin shortcut in the observed session.
* `Ctrl+C`-style interruption is assumed to be handled by the terminal/pty layer.
* Devin reserves the entire terminal surface; there is no built-in split-pane UI.

## Boundaries respected

This document contains only black-box observations from the public CLI help
output and the visible interactive session. It does not include:

* API keys or tokens.
* Private session identifiers.
* Internal source code.
* Proprietary art or logos beyond the visible ASCII header.
* Parsed ANSI sequences or private TUI state.
