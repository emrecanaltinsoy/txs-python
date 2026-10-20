# TUI performance and refactor tracker

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Single tmux snapshot per refresh | done | `TmuxSnapshot.fetch()` |
| 1b | Debounced filter rebuilds (~200ms) | done | `TxsApp._schedule_filter_refresh()` |
| 2 | Per-session pane path map (Sessions) | done | `TmuxSnapshot.window_for_path()` |
| 3 | Config cache on `r` — mtime only | done | `reload_config_if_changed()` |
| 4 | Settings read once per refresh | done | `load_tui_settings()` / `TuiRefreshBundle` |
| 5 | Cache `get_project_worktrees(path)` | done | Cleared each `fetch_refresh_bundle()` |
| 6 | Cache `is_bare_repo(path)` | done | Same refresh-scoped cache |
| 7 | N+1 in `get_active_worktrees()` (fzf) | done | `_git_dir_for_path` + worktree cache |
| 8 | Preview capture debounce | n/a | No live timer; see `PreviewPanel.refresh_preview` |
| 9 | Shared tree helpers on `TxsTreePanel` | done | `subsequence_match`, expand/restore/cursor |
| 10 | `ProjectConfig` name index | done | `_projects_by_name` on parse |
| 11 | TUI refresh orchestration | done | `src/txs/tui/sync.py` |
| 12 | Lazy startup (layout first, staged panels) | done | Worker fetch + Sessions → Agents → Projects |

## Refresh flow

1. Optional `maybe_reload_config()` (mtime check on `projects.conf`).
2. `fetch_refresh_bundle()` — clear git caches, one tmux snapshot, one settings read.
3. All panels `refresh_data(..., bundle)`.

## Startup (lazy)

1. `compose()` paints empty trees immediately; panel titles show `…` while loading.
2. Background worker runs `fetch_refresh_bundle()`.
3. Main thread, one frame apart: Sessions (+ preview) → Agents → Projects → cursors.
4. Manual `r` still runs a full synchronous refresh.
