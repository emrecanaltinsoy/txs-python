test:
  uv run pytest -v

check:
  prek run

reinstall:
  uv tool install --reinstall .

install-hooks:
  uv tool run prek install -f --hook-type pre-commit
