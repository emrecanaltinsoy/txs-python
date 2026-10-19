# txs

<p align="center">
  <a href="https://github.com/emrecanaltinsoy/txs-python/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/emrecanaltinsoy/txs-python/ci.yml?logo=github&label=ci-check" alt="GitHub Actions Workflow Status"></a>
  <a href="https://github.com/emrecanaltinsoy/txs-python/releases"><img src="https://img.shields.io/github/v/release/emrecanaltinsoy/txs-python?display_name=release" alt="GitHub Release"></a>
  <a href="https://github.com/emrecanaltinsoy/txs-python/blob/main/LICENSE"><img src="https://img.shields.io/github/license/emrecanaltinsoy/txs-python" alt="GitHub License"></a>
</p>

A command-line tool to manage tmux sessions from predefined project directories.
This is a Python rewrite of [txs](https://github.com/emrecanaltinsoy/txs), the original bash implementation.
Inspired by [ThePrimeagen's tmux-sessionizer](https://github.com/ThePrimeagen/tmux-sessionizer) and [jrmoulton's tmux-sessionizer](https://github.com/jrmoulton/tmux-sessionizer), tailored to my workflow for managing multiple projects in separate tmux sessions with custom layouts.

txs lets you define your projects in a simple INI-style configuration file and
quickly create, switch to, list, or kill tmux sessions. It includes an
interactive fuzzy-finder picker powered by fzf.

It also includes a helper command to clone repositories as bare repos with a
default worktree so you can keep using Git worktrees cleanly.

## Features

- **Interactive session picker** — fuzzy-find and switch between projects with fzf
- **Bare repo worktree support** — clone, list, and switch between worktrees
- **INI-style configuration** — define projects with paths, custom session names, and on-create commands
- **Multi-line on_create** — run multiple commands when a session is first created
- **Context-aware** — works both inside and outside tmux
- **Shell completions** — tab completion for Bash and Zsh (auto-generated on install)

## Dependencies

| Dependency | Required |
|------------|----------|
| Python     | Yes (≥ 3.10) |
| tmux       | Yes      |
| fzf        | No (needed for interactive mode) |

## Installation

### uv (recommended)

```sh
uv tool install txs-python
```

### pip

```sh
pip install txs-python
```

### From source

```sh
git clone https://github.com/emrecanaltinsoy/txs-python.git
cd txs-python
uv tool install .
```

Or with make:

```sh
make install
```

You can change the install prefix:

```sh
make install PREFIX=/usr/local
```

Shell completions are generated automatically during `make install`. To enable
them, add one of these to your shell rc file:

```sh
# zsh
[[ -f "$HOME/.local/share/txs/completions/txs.zsh" ]] && source "$HOME/.local/share/txs/completions/txs.zsh"

# bash
[[ -f "$HOME/.local/share/txs/completions/txs.bash" ]] && source "$HOME/.local/share/txs/completions/txs.bash"
```

## Uninstallation

```sh
make uninstall
```

This removes txs but keeps your configuration.

## Configuration

txs reads project definitions from `$HOME/.config/txs/projects.conf`. An example
config is installed automatically on first install.

```ini
[DEFAULT]

[my-project]
path = ~/projects/my-project
session_name = myproj
on_create = nvim .

[webapp]
path = ~/projects/webapp
on_create = tmux split-window -v -l 20
    tmux split-window -h -d
    tmux send-keys -t 3 "npm run dev" Enter
    tmux select-pane -t 1
    nvim .
```

### Configuration keys

| Key            | Required | Description                                                    |
|----------------|----------|----------------------------------------------------------------|
| `path`         | Yes      | Directory path for the project (`~` is expanded)               |
| `session_name` | No       | Custom tmux session name (defaults to section name)            |
| `on_create`    | No       | Commands to run after session creation (supports multi-line)   |
| `max_depth`    | No       | Scan subdirectories up to this depth for git repos (default 0) |

The `[DEFAULT]` section provides fallback values for all projects. Dots and
colons in session names are automatically replaced with underscores.

### Settings file

Tool-level settings live in `$HOME/.config/txs/config`. Simple `key = value` format:

```ini
auto_add_clone = true
fzf_height = 50%
```

| Setting          | Default | Description                                              |
|------------------|---------|----------------------------------------------------------|
| `auto_add_clone` | `true`  | Automatically add cloned bare repos to `projects.conf`   |
| `fzf_height`     | `50%`   | Height of fzf picker (percentage or line count)          |

For additional fzf customization (colors, keybindings, layout, etc.), use the
`FZF_DEFAULT_OPTS` environment variable. See `man fzf` for available options.

## Usage

```text
txs                            Interactive fuzzy-finder session picker

Session management:
  txs attach [name] [worktree]   Attach to a session / open a worktree
  txs switch                     Pick from open sessions/windows only
  txs kill [name]                Kill a session (interactive picker when no arg)
  txs kill window                Kill a specific window across all sessions
  txs ls [sessions|projects|worktrees]
                                 List sessions, projects, and/or worktrees

Worktree management (run from any git repo):
  txs wt add [branch]            Create a worktree (prompts if omitted)
  txs wt remove [branch]         Remove a worktree (picker if omitted)
  txs wt list                    List worktrees

Project configuration:
  txs add [path]                 Add a directory to the config (default: .)
  txs remove <name>              Remove a project from the config
  txs clone-bare <url> [name]    Clone as bare repo + create default worktree
  txs config [projects|settings] Open a config file in $EDITOR

Other:
  txs version                    Show version
  txs update                     Update txs to the latest version
  txs --help                     Show help

Aliases:
  list      -> ls
  sessions  -> ls sessions
  projects  -> ls projects
```

### Clone Bare For Worktrees

`txs clone-bare <repo-url> [folder-name]` creates a repository layout suited
for worktree-heavy workflows:

- clones the repository as a bare repo into `.bare/`
- writes `.git` to point at `./.bare`
- fetches remote branches with a full branch refspec
- creates a default branch worktree (origin HEAD, then `main`, then `master`)

```sh
txs clone-bare git@github.com:org/repo.git
```

This creates `./repo`, stores git data in `./repo/.bare`, and checks out the
default branch into `./repo/repo.<branch>`.

### Worktree Management

`txs wt` manages worktrees for any git repository. Run it from inside the repo
(or any of its worktrees). No configuration required.

**Bare repos** (created via `txs clone-bare`): worktrees are placed inside the
repo directory.

**Normal repos**: worktrees are created as sibling directories named
`<repo>.<branch>`.

```sh
# Create a worktree (fetches from origin first)
txs wt add feature-login

# Remove a worktree and its branch
txs wt remove feature-login

# Remove the worktree but keep the branch
txs wt remove --keep-branch feature-login

# List worktrees for the current repo
txs wt list
```

When creating a worktree, txs checks for a matching remote branch first. If
`origin/<branch>` exists, the local branch is set up to track it. Otherwise a
new branch is created from HEAD.

When removing, the branch is deleted by default; pass `--keep-branch` / `-k`
to keep it. In interactive mode (no arguments), you are prompted to confirm
branch deletion.

## Keybindings

txs pairs well with tmux popups and editor keymaps. Here are some examples:

### tmux

```sh
bind-key -r C-s display-popup -E -w 80% -h 70% "txs"
bind-key -r C-k display-popup -E -w 80% -h 70% "txs kill"
bind-key -r C-w display-popup -E -w 80% -h 70% "txs wt add"
bind-key -r C-r display-popup -E -w 80% -h 70% "txs wt remove"
```

### Neovim

```lua
vim.keymap.set("n", "<leader>tt", function()
  if vim.env.TMUX then
    vim.fn.system('tmux display-popup -E -w 80% -h 70% "txs"')
  end
end, { desc = "Start txs" })

vim.keymap.set("n", "<leader>tk", function()
  if vim.env.TMUX then
    vim.fn.system('tmux display-popup -E -w 80% -h 70% "txs kill"')
  end
end, { desc = "Kill session" })

vim.keymap.set("n", "<leader>ta", function()
  if vim.env.TMUX then
    vim.fn.system('tmux display-popup -E -w 80% -h 70% "txs wt add"')
  end
end, { desc = "Add worktree" })

vim.keymap.set("n", "<leader>tr", function()
  if vim.env.TMUX then
    vim.fn.system('tmux display-popup -E -w 80% -h 70% "txs wt remove"')
  end
end, { desc = "Remove worktree" })
```

## License

[GPL-3.0](LICENSE)
