@echo off
rem FINN: setup, offline tests, LIVE smoke test (writes smoke_result.txt), then starts the app at http://localhost:8000
powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\run_windows.ps1"
