@echo off
setlocal
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py "%~dp0configure.py" %*
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        python "%~dp0configure.py" %*
    ) else (
        echo Python was not found. Install Python 3 from https://www.python.org/downloads/
        echo and make sure "Add python.exe to PATH" is checked during installation, then
        echo run this script again.
        exit /b 1
    )
)
