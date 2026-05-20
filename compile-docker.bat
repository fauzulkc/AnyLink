@echo off
title WSL Linker - Standalone Docker Compiler
echo ========================================================
echo   WSL Linker - Standalone Docker Compiler Wrapper
echo ========================================================
echo.
echo Running PyInstaller inside an isolated Windows-on-Wine 
echo Docker container to compile your EXE. No local python
echo libraries will be touched or installed on your host!
echo.
echo Pulling compiler container and compiling wsl_linker_gui.py...
docker run --rm -v "d:\AI Stuff\projects\fauzul\wsl-linker:/src/" batonogov/pyinstaller-windows "pip install customtkinter && pyinstaller --onefile --noconsole --collect-all customtkinter --name 'WSL Linker' wsl_linker_gui.py"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Docker compilation failed. Ensure Docker is running.
    pause
    exit /b %errorlevel%
)
echo.
echo ========================================================
echo   ✔ SUCCESS! Compiled GUI Executable Inside Docker!
echo ========================================================
echo.
echo You can find your single-file executable at:
echo D:\AI Stuff\projects\fauzul\wsl-linker\dist\WSL Linker.exe
echo.
pause
