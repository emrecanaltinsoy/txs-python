"""
Config parsing — mirrors config.sh.

projects.conf  INI-style project definitions.
config         Simple key=value settings file.

Public API
----------
parse_config()                  -> ProjectConfig   (cached per-process)
get_project_prop(cfg, name, prop) -> str
find_project_for_session(cfg, session) -> str | None
is_explicit_project_path(cfg, path) -> bool
build_depth_index(cfg)          (populates cfg._depth_index in-place)
find_depth_owner(cfg, dp_name)  -> tuple[str, str] | None
expand_path(path)               -> str
get_txs_setting(key)            -> str
invalidate_config_cache()
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from txs.log import warn

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "txs"
CONFIG_FILE = _CONFIG_DIR / "projects.conf"
SETTINGS_FILE = _CONFIG_DIR / "config"


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
    # Built lazily by build_depth_index().
    _depth_index: dict[str, tuple[str, str]] | None = field(default=None, repr=False)
    _depth_index_built: bool = field(default=False, repr=False)

    # fast lookup by name
    def _by_name(self, name: str) -> Project | None:
        for p in self.projects:
            if p.name == name:
                return p
        return None


# ---------------------------------------------------------------------------
# Config cache
# ---------------------------------------------------------------------------

_cache: ProjectConfig | None = None


def invalidate_config_cache() -> None:
    global _cache
    _cache = None


def parse_config(config_file: Path | None = None) -> ProjectConfig:
    """Parse projects.conf and return a ProjectConfig (cached after first call)."""
    global _cache
    if _cache is not None and config_file is None:
        return _cache

    cf = config_file or CONFIG_FILE

    if not cf.exists():
        from txs.log import error

        error(f"Config file not found: {cf}")
        raise SystemExit(1)

    # configparser handles multiline values (indented continuation → joined with \n)
    # RawConfigParser skips interpolation (% signs in paths etc.)
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # preserve key case

    # configparser requires [DEFAULT] to be exactly that — which matches our format.
    # We read the raw file first so we can warn on unknown keys, then use configparser
    # for the actual parsing.
    parser.read(cf, encoding="utf-8")

    cfg = ProjectConfig()

    # DEFAULT section
    defaults = dict(parser.defaults())
    _warn_unknown_keys(defaults, {"on_create", "session_name"}, "DEFAULT")
    cfg.default_on_create = defaults.get("on_create", "")
    cfg.default_session_name = defaults.get("session_name", "")

    # Project sections
    for section in parser.sections():
        keys = dict(parser.items(section))
        # configparser merges DEFAULT into every section — remove them for the
        # unknown-key check, then we apply fallbacks explicitly.
        section_only_keys = {
            k: v
            for k, v in keys.items()
            if k not in defaults or parser.has_option(section, k)
        }
        _warn_unknown_keys(
            section_only_keys,
            {"path", "session_name", "on_create", "max_depth"},
            section,
        )
        depth_raw = keys.get("max_depth", "0")
        try:
            depth = int(depth_raw)
        except ValueError:
            warn(f"Invalid max_depth '{depth_raw}' in [{section}], using 0")
            depth = 0

        proj = Project(
            name=section,
            path=keys.get("path", ""),
            session_name=keys.get("session_name", ""),
            on_create=keys.get("on_create", ""),
            max_depth=depth,
        )
        cfg.projects.append(proj)

    if config_file is None:
        _cache = cfg
    return cfg


def _warn_unknown_keys(keys: dict, known: set, section: str) -> None:
    for k in keys:
        if k not in known:
            warn(f"Unknown key '{k}' in [{section}]")


# ---------------------------------------------------------------------------
# Property accessors  (mirrors get_project_prop in config.sh)
# ---------------------------------------------------------------------------


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
    """Expand leading ~ to HOME (mirrors expand_path in config.sh)."""
    if path.startswith("~/") or path == "~":
        return str(Path.home()) + path[1:]
    return path


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
    if cfg._depth_index_built:
        return
    cfg._depth_index_built = True
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


# ---------------------------------------------------------------------------
# Settings file  (mirrors get_txs_setting in config.sh)
# ---------------------------------------------------------------------------


def get_txs_setting(key: str, settings_file: Path | None = None) -> str:
    """Read a key from the simple key=value settings file."""
    sf = settings_file or SETTINGS_FILE
    if not sf.exists():
        return ""
    for raw in sf.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            # strip inline comment (only when not quoted)
            if not (v.startswith(('"', "'"))):
                v = v.split("#")[0].strip()
            if k == key:
                return v
    return ""
