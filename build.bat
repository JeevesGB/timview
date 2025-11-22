@echo off
set EXENAME=TIMView
set ICONFILE=icon.ico
pip install -r requirements.txt
REM Build timview-v2.py into a single EXE with an icon and no console window
pyinstaller --onefile --windowed --icon "%ICONFILE%" --name "%EXENAME%" timview-v2.py

echo.
echo %EXENAME% built!
pause
