home := env("HOME")
prefix := env("PREFIX", home / ".local")
bindir := prefix / "bin"
sharedir := prefix / "share/txs/completions"

test cov="":
  #!/usr/bin/env bash
  set -euo pipefail
  if [ -n "{{cov}}" ]; then
    uv run pytest -v --cov=. --cov-report=term-missing
  else
    uv run pytest -v
  fi

check:
  prek run

reinstall:
  uv tool install --reinstall .

install-hooks:
  uv tool run prek install -f --hook-type pre-commit

completion:
  mkdir -p "{{bindir}}" "{{sharedir}}"
  @# Generate completions from the installed binary
  @env _TXS_COMPLETE=source_bash "{{bindir}}/txs" > "{{sharedir}}/txs.bash" 2>/dev/null || true
  @env _TXS_COMPLETE=source_zsh "{{bindir}}/txs"  > "{{sharedir}}/txs.zsh"  2>/dev/null || true
  @echo "Generated shell completions in {{sharedir}}"
  @echo ""
  @echo "Installed txs to {{bindir}}/txs"
  @echo ""
  @echo "To enable shell completions, add to your shell rc:"
  @echo "  zsh:  source {{sharedir}}/txs.zsh"
  @echo "  bash: source {{sharedir}}/txs.bash"
