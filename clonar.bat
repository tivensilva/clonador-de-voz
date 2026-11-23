@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Primero corre instalar.bat
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0clonar.py" %*
