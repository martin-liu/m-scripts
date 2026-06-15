# Talon Voice Config for m-scripts

Minimal Talon configuration for Ghostty + Zellij + Claude Code / opencode voice control.

**No community scripts. Ghostty-only.**

## Install

```bash
bin/setup-talon.sh
```

Then restart Talon and focus Ghostty.

## How It Works

- **Talon awake + Ghostty focused + command mode** = terminal commands work
- **Talon awake + other app focused** = nothing happens
- **"talon sleep"** = stop listening everywhere (true sleep, no recognition)
- **Double mouth-pop** (pop pop) = wake up
- Optional fallback: **"talon system activate talon system activate"** = wake up
- **No community scripts** — only your commands exist

## Safety Model

Commands are scoped to Ghostty only. They cannot trigger in:
- Zoom / Meet / Slack
- Browser
- VS Code / other editors
- Finder / any other app

**Before talking to someone:** Say `"talon sleep"`

**Risk:** If Ghostty is focused while you're talking, commands *could* trigger. Use `"talon sleep"` before conversations.

## Core Commands (Ghostty + command mode)

### Zellij Navigation
| Say | Action |
|---|---|
| `z left` / `z right` / `z up` / `z down` | Move focus |
| `tab one` / `tab two` / ... / `tab ten` | Switch to tab (guarded: won't switch if tab doesn't exist) |
| `tab last` | Switch to last tab |
| `tab tab` | Toggle between current tab and previously visited tab |
| `z next` / `z previous` | Next/previous tab |
| `z new pane` | New pane |
| `z close pane` | Close pane |
| `z full screen` | Toggle fullscreen |
| `z floating` | Toggle floating panes |

### Text Editing
| Say | Action |
|---|---|
| `term delete` | Backspace 1 char |
| `term delete five` | Backspace 5 chars |
| `chuck word` | Delete previous word |
| `chuck three words` | Delete 3 previous words |
| `chuck next word` | Delete next word |
| `chuck line` / `clear line` | Clear entire line |
| `chuck start` | Delete to line start |
| `chuck end` | Delete to line end |
| `char left` / `char right` | Move 1 char |
| `char five left` | Move 5 chars left |
| `word left` / `word right` | Move 1 word |
| `word three left` | Move 3 words left |
| `line start` / `line end` | Jump to start/end |
| `opt up` / `opt down` | Select option up/down (arrow keys) |
| `term copy` / `term paste` | Clipboard |
| `term undo` | Undo |
| `submit` | Press Enter |
| `term cancel` | Press Escape |

### Dictation (Voice-to-Text)
| Say | Action |
|---|---|
| `dictate` | Sleep Talon, record speech, transcribe locally, paste into Ghostty |
| `submit` | Press Enter after reviewing pasted text |

**How it works:**
1. Say `"dictate"` **alone** (don't say the prompt yet)
2. Talon immediately stops listening (speech disabled)
3. Hear Tink sound → **now** start speaking your prompt
4. Stop talking (~1.5s silence auto-stops recording)
5. Hear Basso sound → text appears
6. Talon wakes automatically → you can immediately say `"submit"`, `"term delete"`, etc.

**Important:** Wait for the Tink sound before speaking your prompt. If you say `"dictate review the code"` without pausing, Talon may buffer "review the code" before speech is disabled.

**Dependencies:**
- Talon.app with Conformer D engine
- `sox` / `rec` (installed by setup-talon.sh)
- `whisper-cli` (installed by setup-talon.sh)
- Whisper model at `~/.config/whisper/ggml-small.bin`

### Global Commands (any app)
| Say | Action |
|---|---|
| `talon sleep` | Stop listening |
| Double mouth-pop (pop pop) | Wake up |
| `talon system activate talon system activate` | Wake up (fallback) |

## Files

- `apps/ghostty.py` — Ghostty app detection
- `zellij.py` / `zellij.talon` — Zellij navigation
- `edit.py` / `edit.talon` — Text editing commands
- `dictation.py` / `dictation.talon` — Voice-to-text dictation
- `sleep.py` / `sleep.talon` / `wake.talon` — Sleep/wake controls
- `bin/dictate-terminal.sh` — Recording/transcription script
