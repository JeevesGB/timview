@echo off
set EXENAME=TIMView

REM Build gtd.py into a single EXE with no console window
 pyinstaller --onefile --windowed --name TIMView --exclude-module tkinter --exclude-module test timview-v2.py

echo.
echo %EXENAME% built!
pause