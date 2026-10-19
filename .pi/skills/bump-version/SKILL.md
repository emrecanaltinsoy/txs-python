---
name: bump-version
description: >-
  Bump TXS_VERSION in src/txs/__init__.py with semantic versioning, commit as
  "chore(release): vX.Y.Z", and create a matching git tag. Use when the user
  says "release", "bump version", "new version", "cut a release", or invokes
  /bump-version.
---

# bump-version

Releases a new version of txs-python. Steps:

1. **Read current version** from `src/txs/__init__.py` — find the `TXS_VERSION =` line.

2. **Determine bump type** — if the user did not specify (major / minor / patch), ask with `ask_user_question` before proceeding.

3. **Compute new version** by incrementing the appropriate segment and zeroing lower ones:
   - patch: `1.0.0` → `1.0.1`
   - minor: `1.0.0` → `1.1.0`
   - major: `1.0.0` → `2.0.0`

4. **Update both version locations**:
   - `src/txs/__init__.py` — replace the `TXS_VERSION = "..."` line
   - `pyproject.toml` — replace the `version = "..."` line under `[project]`

5. **Stage and commit**:

   ```bash
   git add src/txs/__init__.py pyproject.toml
   git commit -m "chore(release): v<NEW_VERSION>"
   ```

6. **Create annotated tag**:

   ```bash
   git tag -a "v<NEW_VERSION>" -m "v<NEW_VERSION>"
   ```

7. **Report** the new version, commit hash, and tag to the user.

## Rules

- Never bump without explicit confirmation of the bump type.
- Do not push — just commit and tag locally.
- Do not touch any file other than `src/txs/__init__.py` and `pyproject.toml`.
- If the working tree has unstaged changes, warn the user before proceeding.
