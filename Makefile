PREFIX    ?= $(HOME)/.local
CONFDIR   ?= $(HOME)/.config/txs

BINDIR    = $(PREFIX)/bin
VENVDIR   = $(PREFIX)/lib/txs-venv
SHAREDIR  = $(PREFIX)/share/txs/completions

.PHONY: install uninstall test lint help

install:
	mkdir -p "$(BINDIR)" "$(SHAREDIR)"
	python3 -m venv "$(VENVDIR)"
	"$(VENVDIR)/bin/pip" install --quiet .
	ln -sf "$(VENVDIR)/bin/txs" "$(BINDIR)/txs"
	@# Generate completions from the installed binary
	@"$(BINDIR)/txs" --show-completion bash > "$(SHAREDIR)/txs.bash" 2>/dev/null || true
	@"$(BINDIR)/txs" --show-completion zsh  > "$(SHAREDIR)/txs.zsh"  2>/dev/null || true
	@echo "Generated shell completions in $(SHAREDIR)"
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
	@echo "Installed txs to $(BINDIR)/txs"
	@echo ""
	@echo "To enable shell completions, add to your shell rc:"
	@echo "  zsh:  source $(SHAREDIR)/txs.zsh"
	@echo "  bash: source $(SHAREDIR)/txs.bash"

uninstall:
	rm -f "$(BINDIR)/txs"
	rm -rf "$(VENVDIR)"
	rm -rf "$(PREFIX)/share/txs"
	@echo "Uninstalled txs (config at $(CONFDIR) was kept)"

test:
	uv run pytest

lint:
	uv run ruff check src/ tests/

help:
	@echo "txs Makefile (Python)"
	@echo ""
	@echo "Targets:"
	@echo "  install     Install txs to PREFIX (default: $(HOME)/.local)"
	@echo "  uninstall   Remove txs (keeps config)"
	@echo "  test        Run test suite (pytest)"
	@echo "  lint        Run ruff on src/ and tests/"
	@echo "  help        Show this message"
	@echo ""
	@echo "Variables:"
	@echo "  PREFIX      Installation prefix  (default: $(HOME)/.local)"
	@echo "  CONFDIR     Config directory      (default: $(HOME)/.config/txs)"
