"""
Config parsing.

config.toml is the single source of truth:

    [settings]              tool settings, flat key = value
    [defaults]              values applied to every project unless overridden
    [projects."<name>"]     one table per project

Legacy files (projects.conf, config) are converted once on first use. The
originals are kept with a .bak suffix.

Public API
----------
parse_config()                    -> ProjectConfig   (cached per-process)
get_project_prop(cfg, name, prop) -> str
find_project_for_session(cfg, session) -> str | None
is_explicit_project_path(cfg, path) -> bool
build_depth_index(cfg)            (populates cfg._depth_index in-place)
find_depth_owner(cfg, dp_name)    -> tuple[str, str] | None
expand_path(path)                 -> str
get_txs_setting(key)              -> str
set_txs_setting(key, value)       (edits [settings] in place, keeps comments)
add_project(name, path) / remove_project(name) / project_exists(name)
invalidate_config_cache()
"""

from __future__ import annotations

import configparser
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from txs.log import info, warn

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "txs"
CONFIG_FILE = _CONFIG_DIR / "config.toml"

_SETTINGS_HEADER = "[settings]"
_DEFAULTS_HEADER = "[defaults]"
_PROJECT_KNOWN_KEYS = {"path", "session_name", "on_create", "max_depth"}
_DEFAULT_KNOWN_KEYS = {"on_create", "session_name"}
_TOP_LEVEL_SECTIONS = {"settings", "defaults", "projects"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Project:
    name: str
    path: str = ""
    session_name: str = ""
    on_create: str = ""
    max_depth: int = 0


@dataclass
class ProjectConfig:
    projects: list[Project] = field(default_factory=list)
    default_session_name: str = ""
    default_on_create: str = ""

    # depth owner index: basename -> (project_name, abs_path)
    # None means not yet built.
    _depth_index: dict[str, tuple[str, str]] | None = field(default=None, repr=False)
    _projects_by_name: dict[str, Project] = field(default_factory=dict, repr=False)

    def _by_name(self, name: str) -> Project | None:
        return self._projects_by_name.get(name)

    def _index_projects(self) -> None:
        self._projects_by_name = {p.name: p for p in self.projects}


# ---------------------------------------------------------------------------
# Config cache
# ---------------------------------------------------------------------------

_cache: ProjectConfig | None = None
_config_mtime: float | None = None


def invalidate_config_cache() -> None:
    global _cache, _config_mtime
    _cache = None
    _config_mtime = None


def reload_config_if_changed() -> None:
    """Drop cached config only when projects.conf mtime changed."""
    global _config_mtime
    if not CONFIG_FILE.exists():
        invalidate_config_cache()
        return
    mtime = CONFIG_FILE.stat().st_mtime
    if _cache is not None and _config_mtime == mtime:
        return
    invalidate_config_cache()


# ---------------------------------------------------------------------------
# TOML helpers
# ---------------------------------------------------------------------------

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _toml_value(value: str) -> str:
    """Settings values: booleans and integers stay typed, everything else is a string."""
    if value in ("true", "false"):
        return value
    if re.fullmatch(r"-?\d+", value):
        return value
    return json.dumps(value)


def _project_header(name: str) -> str:
    return f"[projects.{_toml_key(name)}]"


def _read_toml(path: Path) -> dict:
    """Parse a config file, migrating legacy files first. Missing file -> {}."""
    _migrate_legacy(path)
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        warn(f"Invalid TOML in {path}: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Legacy migration (projects.conf + config  ->  config.toml)
# ---------------------------------------------------------------------------


def _read_legacy_settings(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if not value.startswith(('"', "'")):
            value = value.split("#")[0].strip()
        pairs.append((key.strip(), value))
    return pairs


def _migrate_legacy(cf: Path) -> None:
    """Convert projects.conf and config into cf once. Never overwrites cf."""
    if cf.exists():
        return
    legacy_projects = cf.parent / "projects.conf"
    legacy_settings = cf.parent / "config"
    if not legacy_projects.exists() and not legacy_settings.exists():
        return

    lines = ["# txs configuration (migrated from projects.conf and config)", ""]

    if legacy_settings.exists():
        lines.append(_SETTINGS_HEADER)
        for key, value in _read_legacy_settings(legacy_settings):
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
        lines.append("")

    if legacy_projects.exists():
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(legacy_projects, encoding="utf-8")
        defaults = dict(parser.defaults())
        if defaults:
            lines.append(_DEFAULTS_HEADER)
            for key, value in defaults.items():
                lines.append(f"{_toml_key(key)} = {json.dumps(value)}")
            lines.append("")
        for section in parser.sections():
            items = dict(parser.items(section))
            body = {
                k: v for k, v in items.items() if k not in defaults or defaults[k] != v
            }
            lines.append(_project_header(section))
            for key, value in body.items():
                if key == "max_depth" and re.fullmatch(r"\d+", value):
                    lines.append(f"max_depth = {int(value)}")
                else:
                    lines.append(f"{_toml_key(key)} = {json.dumps(value)}")
            lines.append("")

    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    for legacy in (legacy_projects, legacy_settings):
        if legacy.exists():
            legacy.rename(legacy.with_name(legacy.name + ".bak"))
    info(
        f"Migrated settings and projects to [green]{cf}[/green] (old files kept as .bak)"
    )


def parse_config(config_file: Path | None = None) -> ProjectConfig:
    """Parse config.toml and return a ProjectConfig (cached after first call)."""
    global _cache
    if _cache is not None and config_file is None:
        return _cache

    cf = config_file or CONFIG_FILE
    _migrate_legacy(cf)

    if not cf.exists():
        from txs.log import error

        error(f"Config file not found: {cf}")
        raise SystemExit(1)

    try:
        data = tomllib.loads(cf.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        from txs.log import error

        error(f"Invalid TOML in {cf}: {exc}")
        raise SystemExit(1)

    for section in data:
        if section not in _TOP_LEVEL_SECTIONS:
            warn(f"Unknown section '[{section}]' in {cf.name}")

    cfg = ProjectConfig()

    defaults = data.get("defaults") or {}
    _warn_unknown_keys(defaults, _DEFAULT_KNOWN_KEYS, "defaults")
    cfg.default_on_create = str(defaults.get("on_create", ""))
    cfg.default_session_name = str(defaults.get("session_name", ""))

    for name, body in (data.get("projects") or {}).items():
        if not isinstance(body, dict):
            warn(f"Project '{name}' must be a table, skipping")
            continue
        _warn_unknown_keys(body, _PROJECT_KNOWN_KEYS, f"projects.{name}")
        depth_raw = body.get("max_depth", 0)
        try:
            depth = int(depth_raw)
        except (TypeError, ValueError):
            warn(f"Invalid max_depth '{depth_raw}' in [projects.{name}], using 0")
            depth = 0
        cfg.projects.append(
            Project(
                name=name,
                path=str(body.get("path", "")),
                session_name=str(body.get("session_name", "")),
                on_create=str(body.get("on_create", "")),
                max_depth=depth,
            )
        )

    cfg._index_projects()

    if config_file is None:
        global _config_mtime
        _cache = cfg
        _config_mtime = cf.stat().st_mtime
    return cfg


def _warn_unknown_keys(keys: dict, known: set, section: str) -> None:
    for k in keys:
        if k not in known:
            warn(f"Unknown key '{k}' in [{section}]")


def get_project_prop(cfg: ProjectConfig, name: str, prop: str) -> str:
    proj = cfg._by_name(name)
    if proj is None:
        return ""

    match prop:
        case "path":
            return proj.path
        case "session_name":
            sname = proj.session_name or cfg.default_session_name or name
            # tmux replaces '.' and ':' with '_'
            return sname.replace(".", "_").replace(":", "_")
        case "on_create":
            return proj.on_create or cfg.default_on_create
        case "max_depth":
            return str(proj.max_depth)
        case _:
            return ""


def expand_path(path: str) -> str:
    """Expand leading ~ to HOME."""
    return str(Path(path).expanduser())


# ---------------------------------------------------------------------------
# Session / path lookups
# ---------------------------------------------------------------------------


def find_project_for_session(cfg: ProjectConfig, session: str) -> str | None:
    """Return project name whose session_name matches, or None."""
    for proj in cfg.projects:
        if proj.max_depth > 0:
            continue
        sname = get_project_prop(cfg, proj.name, "session_name")
        if sname == session:
            return proj.name
    return None


def is_explicit_project_path(cfg: ProjectConfig, path: str) -> bool:
    """True if path matches a non-depth project's resolved path."""
    for proj in cfg.projects:
        if proj.max_depth > 0:
            continue
        epath = expand_path(proj.path)
        if epath == path:
            return True
    return False


# ---------------------------------------------------------------------------
# Depth index  (mirrors _build_depth_index / find_depth_owner in config.sh)
# ---------------------------------------------------------------------------


def build_depth_index(cfg: ProjectConfig) -> None:
    """Populate cfg._depth_index (last-writer-wins, same as bash version)."""
    if cfg._depth_index is not None:
        return
    cfg._depth_index = {}

    from txs.git import get_depth_projects  # avoid circular import at module level

    for proj in cfg.projects:
        if proj.max_depth <= 0:
            continue
        root = expand_path(proj.path)
        for dp_path, dp_name in get_depth_projects(root, proj.max_depth):
            if is_explicit_project_path(cfg, dp_path):
                continue
            # last-writer-wins
            cfg._depth_index[dp_name] = (proj.name, dp_path)


def find_depth_owner(cfg: ProjectConfig, dp_name: str) -> tuple[str, str] | None:
    """Return (project_name, abs_path) for a depth-discovered repo basename, or None."""
    build_depth_index(cfg)
    assert cfg._depth_index is not None
    return cfg._depth_index.get(dp_name)


def setting_is_true(key: str, settings_file: Path | None = None) -> bool:
    """Return True if a settings key is explicitly set to true."""
    return get_txs_setting(key, settings_file).lower() == "true"


def setting_bool(
    key: str, default: bool = False, settings_file: Path | None = None
) -> bool:
    """Parse a settings key as bool; return default when missing or unrecognized."""
    val = get_txs_setting(key, settings_file).strip().lower()
    if not val:
        return default
    if val == "true":
        return True
    if val == "false":
        return False
    return default


@dataclass(frozen=True)
class TuiSettingsView:
    trees_expanded: bool


def load_tui_settings(settings_file: Path | None = None) -> TuiSettingsView:
    """Read TUI-related settings once (for a refresh cycle)."""
    return TuiSettingsView(
        trees_expanded=setting_bool(
            "tui_trees_expanded", default=True, settings_file=settings_file
        ),
    )


# ---------------------------------------------------------------------------
# Settings  ([settings] table)
# ---------------------------------------------------------------------------


def get_txs_setting(key: str, settings_file: Path | None = None) -> str:
    """Read a key from [settings]; booleans come back as 'true' / 'false'."""
    data = _read_toml(settings_file or CONFIG_FILE)
    value = (data.get("settings") or {}).get(key)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _section_bounds(lines: list[str], header: str) -> tuple[int, int] | None:
    """Return (first body line, first line after the section) for a table header."""
    for i, line in enumerate(lines):
        if line.strip() == header:
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if lines[j].lstrip().startswith("["):
                    end = j
                    break
            return i + 1, end
    return None


def _is_assignment(line: str, key: str) -> bool:
    return re.match(rf'^\s*"?{re.escape(key)}"?\s*=', line) is not None


def set_txs_setting(key: str, value: str, settings_file: Path | None = None) -> None:
    """Set a key in [settings], editing only that line so comments survive."""
    cf = settings_file or CONFIG_FILE
    _migrate_legacy(cf)
    lines = cf.read_text(encoding="utf-8").splitlines() if cf.exists() else []
    assignment = f"{_toml_key(key)} = {_toml_value(value)}"

    bounds = _section_bounds(lines, _SETTINGS_HEADER)
    if bounds is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [_SETTINGS_HEADER, assignment]
    else:
        begin, end = bounds
        for i in range(begin, end):
            if _is_assignment(lines[i], key):
                lines[i] = assignment
                break
        else:
            insert_at = begin
            for i in range(begin, end):
                if lines[i].strip():
                    insert_at = i + 1
            lines.insert(insert_at, assignment)

    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Project writers  ([projects."<name>"] tables)
# ---------------------------------------------------------------------------


def project_exists(name: str, config_file: Path | None = None) -> bool:
    data = _read_toml(config_file or CONFIG_FILE)
    return name in (data.get("projects") or {})


def add_project(name: str, path: str, config_file: Path | None = None) -> None:
    cf = config_file or CONFIG_FILE
    _migrate_legacy(cf)
    text = cf.read_text(encoding="utf-8") if cf.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(
        f"{text}\n{_project_header(name)}\npath = {json.dumps(path)}\n",
        encoding="utf-8",
    )


def remove_project(name: str, config_file: Path | None = None) -> None:
    """Delete a project's table (header through the next table or EOF)."""
    cf = config_file or CONFIG_FILE
    _migrate_legacy(cf)
    lines = cf.read_text(encoding="utf-8").splitlines()
    header = _project_header(name)
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].lstrip().startswith("["):
            end = j
            break
    del lines[start:end]
    while lines and not lines[-1].strip():
        lines.pop()
    cf.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
