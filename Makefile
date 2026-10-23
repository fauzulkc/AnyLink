# WSL Linker - Development Makefile
# Designed for both Windows environments running Make (via Git Bash, MSYS2, Chocolatey) and Linux/macOS.

.PHONY: run run-experimental build-docker build-local build-experimental clean status help

help:
	@echo "========================================================================"
	@echo "                  WSL LINKER DEVELOPMENT TASKS                          "
	@echo "========================================================================"
	@echo "  make run                - Launch the WSL Linker GUI locally in Python"
	@echo "  make run-experimental   - Launch the Experimental Suite GUI in Python"
	@echo "  make build-local        - Compile GUI into standalone EXE (WSL Linker.exe)"
	@echo "  make build-experimental - Compile Experimental Suite EXE (WSL Linker Experimental.exe)"
	@echo "  make build-docker       - Compile GUI into standalone EXE via Wine Docker"
	@echo "  make clean              - Clean build artifacts (build/, dist/, spec files)"
	@echo "  make status             - Check local Git version status"
	@echo "========================================================================"

run:
	python wsl_linker_gui.py

run-experimental:
	python experimental_linker_gui.py

build-docker:
	docker run --rm -v "d:\AI Stuff\projects\fauzul\wsl-linker:/src/" batonogov/pyinstaller-windows "pip install customtkinter && pyinstaller --onefile --noconsole --collect-all customtkinter --name 'WSL Linker' wsl_linker_gui.py"

build-local:
	pip install customtkinter pyinstaller
	pyinstaller --onefile --noconsole --collect-all customtkinter --name "WSL Linker" wsl_linker_gui.py

build-experimental:
	pip install customtkinter pyinstaller
	pyinstaller "WSL Linker Experimental.spec" --noconfirm

clean:
	@echo "Cleaning build directories..."
	@rm -rf build dist "WSL Linker.spec" 2>/dev/null || rmdir /s /q build dist 2>nul || echo "Done"

status:
	git status
