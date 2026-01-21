PREFIX ?= /opt/homebrew
BINDIR ?= $(PREFIX)/bin
TARGET ?= ytdl-audiobook
SCRIPT := ytdl_audiobook_scraper.py

.PHONY: build install uninstall lint

build: lint ## Copy the CLI into $(BINDIR)/$(TARGET)
	install -d $(BINDIR)
	install -m 755 $(SCRIPT) $(BINDIR)/$(TARGET)

install: build ## Alias for build (Homebrew conventions)

uninstall: ## Remove the previously installed binary
	rm -f $(BINDIR)/$(TARGET)

lint:
	python3 -m py_compile $(SCRIPT)
