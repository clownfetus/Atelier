@echo off
rem Builds the Windows installer: dist\AtelierSetup.exe. All logic lives in scripts\build.py;
rem this only picks the repository's .venv so the pinned Python is used.
rem   BUILD.bat                 build the version in .\version
rem   BUILD.bat --version 1.2.0 set the version first
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo No .venv found. Create it with Python 3.15 and install requirements-build.txt; see docs\DEVELOPMENT.md
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\build.py" --platform windows %*
exit /b %ERRORLEVEL%
