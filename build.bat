@echo off
set EXENAME=TIMView

REM Build timview-v2.py into a single EXE with no console window
pyinstaller --onefile --windowed --name %EXENAME% timview-v2.py

echo.
echo %EXENAME% built!
pause
