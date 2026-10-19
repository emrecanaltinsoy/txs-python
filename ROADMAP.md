# Roadmap

Ideas and planned features, roughly ordered by priority.

---

## Near-term

### `on_attach` hook

A companion to `on_create` that runs every time you attach to a session, not just on creation.
Useful for activating virtualenvs, loading `.env` files, `nvm use`, `conda activate`, etc.

```ini
[my-project]
path = ~/projects/my-project
on_create = tmux split-window -v
    nvim .
on_attach = source .venv/bin/activate
```

### Tags + picker filtering

Tag projects and filter the fzf picker by typing `@tag`.
Especially useful when `max_depth` surfaces 20+ repos and you want to narrow to a subset.

```ini
[api]
path = ~/projects/api
tags = work, backend

[frontend]
path = ~/projects/frontend
tags = work, frontend
```

### `txs rename <old> <new>`

Rename a project in the config and the live tmux session in one command.

### `txs import <dir>`

Bulk-add all git repos found directly inside a directory, without setting `max_depth`.
One-shot alternative to `txs add` for bootstrapping a new machine.

### fzf preview pane

Show `git log --oneline` or the project `README.md` when hovering over an entry in the picker.
Controlled via `config`:

```ini
fzf_preview = true
```

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

### Panels

- **Active sessions** — live tmux sessions with their open windows
- **All projects** — everything from `projects.conf`, active/inactive status
- **Agents** — active AI agents per session, with status (idle / thinking / waiting)
- **Preview** — git log, branch info, or README for the focused item
