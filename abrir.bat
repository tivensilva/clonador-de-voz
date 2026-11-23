@echo off
title Clonador de voz
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo.
  echo  Todavia no esta instalado. Primero haz doble clic en instalar.bat
  echo.
  pause
  exit /b 1
)
echo.
echo  Abriendo el Clonador de voz... el navegador se abre solo en unos segundos.
echo  Deja esta ventana abierta mientras lo usas. Para apagarlo, cierrala.
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
pause
