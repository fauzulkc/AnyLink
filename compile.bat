@echo off
title WSL Linker - Standalone Executable Compiler
echo ========================================================
echo        WSL Linker - Standalone Compiler Wrapper
echo ========================================================
echo.
echo This script will package wsl_linker_gui.py into a single,
echo standalone executable file "WSL Linker.exe" (zero-dependency).
echo.
echo 1. Installing packaging library (PyInstaller & CustomTkinter)...
pip install pyinstaller customtkinter
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install dependencies. Please verify Python and Pip are on your PATH.
    pause
    exit /b %errorlevel%
)

echo.
echo 2. Compiling the Fluent GUI App (This may take ~20-30 seconds)...
pyinstaller --onefile --noconsole --collect-all customtkinter --name "WSL Linker" wsl_linker_gui.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Compilation failed.
    pause
    exit /b %errorlevel%
)

echo.
echo ========================================================
echo   ✔ SUCCESS! Standalone GUI Executable Created!
echo ========================================================
echo.
echo You can find your single-file executable at:
echo D:\AI Stuff\projects\fauzul\wsl-linker\dist\WSL Linker.exe
echo.
echo You can now copy and distribute "WSL Linker.exe" to any 
echo Windows PC, and it will run instantly with zero setup.
echo ========================================================
echo.
pause
