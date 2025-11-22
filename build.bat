@echo off 
title Building TIMView EXE...

REM ---- CLEAN OLD BUILDS ----
if exist build rmdir /s /q build 
if exist dist rmdir /s /q dist 

echo.
echo === BUILDING EXE ===
echo.

REM ---- BUILD EXE ----
