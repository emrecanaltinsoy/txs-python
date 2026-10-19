# Roadmap

Ideas and planned features, roughly ordered by priority.

---

## Near-term

---

## TUI (Textual)

A lazygit-style terminal UI built with [Textual](https://github.com/Textualize/textual)
as an alternative to the fzf picker. Invoked via `txs tui` (or replaces `txs` with no args).

### Layout

```text
┌─ Active sessions ──────┐ ┌─ All projects ─────────┐
│ * myproject  [nvim]    │ │   api          inactive │
│ * api        [nvim,    │ │ * myproject    active   │
│              server]   │ │   dotfiles     inactive │
│                        │ │   frontend     inactive │
└────────────────────────┘ └────────────────────────┘
┌─ Agents ───────────────┐ ┌─ Preview ──────────────┐
│ myproject  pi (idle)   │ │ branch: main            │
│ api        claude      │ │ 3a1b2c feat: add login  │
│            (thinking)  │ │ 9f4e1d fix: auth bug    │
│                        │ │ 1d2c3b chore: cleanup   │
└────────────────────────┘ └────────────────────────┘
```

### Interactions

| Key | Action |
|-----|--------|
| `h/j/k/l` | Navigate between panels and items |
| `Enter` | Attach to session / create and attach |
| `/` | Filter current panel |
| `x` | Kill session |
| `n` | New session from project |
| `a` | Launch agent in focused session |
| `q` / `Esc` | Quit |

### Tags

User-defined tags on projects for filtering panels with `@tag`.

```ini
[api]
path = ~/projects/api
tags = work, backend
```

### Panels

- **Active sessions** — live tmux sessions with their open windows
- **All projects** — everything from `projects.conf`, active/inactive status
- **Agents** — active AI agents per session, with status (idle / thinking / waiting).
  Detect by scanning tmux pane process names for known agents (pi, claude, codex, etc.).
  Keybindings: `n` launch agent in current session, `N` pick any active session to launch in.
  Open question: one window per agent vs. grouped agents panel — to be decided when implemented.
- **Preview** — git log, branch info, or `README.md` for the focused item; replaces the fzf preview pane concept
