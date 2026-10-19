PREFIX    ?= $(HOME)/.local
CONFDIR   ?= $(HOME)/.config/txs

BINDIR    = $(PREFIX)/bin
SHAREDIR  = $(PREFIX)/share/txs/completions

# Use uv if available, otherwise fall back to pip
UV        := $(shell command -v uv 2>/dev/null)
PIP_CMD   := $(if $(UV),uv pip install,pip install)

.PHONY: install uninstall test lint help

install:
	mkdir -p "$(BINDIR)" "$(SHAREDIR)"
	$(PIP_CMD) --prefix "$(PREFIX)" .
	@# Generate completions from the installed binary
	@TXS_BIN="$(BINDIR)/txs-python"; \
	if [ -x "$$TXS_BIN" ]; then \
		$$TXS_BIN --show-completion bash > "$(SHAREDIR)/txs.bash" 2>/dev/null || true; \
		$$TXS_BIN --show-completion zsh  > "$(SHAREDIR)/txs.zsh"  2>/dev/null || true; \
		echo "Generated shell completions in $(SHAREDIR)"; \
	fi
	@if [ ! -f "$(CONFDIR)/projects.conf" ]; then \
		install -Dm644 examples/projects.conf.example "$(CONFDIR)/projects.conf"; \
		echo "Installed example config to $(CONFDIR)/projects.conf"; \
	else \
		echo "Kept existing config at $(CONFDIR)/projects.conf"; \
	fi
	@if [ ! -f "$(CONFDIR)/config" ]; then \
		install -Dm644 examples/config.example "$(CONFDIR)/config"; \
		echo "Installed example settings to $(CONFDIR)/config"; \
	else \
		echo "Kept existing settings at $(CONFDIR)/config"; \
	fi
	@echo ""
	@echo "Installed txs-python to $(BINDIR)/txs-python"
	@echo ""
	@echo "To enable shell completions, add to your shell rc:"
	@echo "  zsh:  source $(SHAREDIR)/txs.zsh"
	@echo "  bash: source $(SHAREDIR)/txs.bash"

uninstall:
	$(PIP_CMD) uninstall txs -y 2>/dev/null || true
	rm -f "$(BINDIR)/txs-python"
	rm -rf "$(PREFIX)/share/txs"
	@echo "Uninstalled txs-python (config at $(CONFDIR) was kept)"

test:
	uv run pytest

lint:
	uv run ruff check src/ tests/

help:
	@echo "txs Makefile (Python)"
	@echo ""
	@echo "Targets:"
	@echo "  install     Install txs-python to PREFIX (default: $(HOME)/.local)"
	@echo "  uninstall   Remove txs-python (keeps config)"
	@echo "  test        Run test suite (pytest)"
	@echo "  lint        Run ruff on src/ and tests/"
	@echo "  help        Show this message"
	@echo ""
	@echo "Variables:"
	@echo "  PREFIX      Installation prefix  (default: $(HOME)/.local)"
	@echo "  CONFDIR     Config directory      (default: $(HOME)/.config/txs)"
