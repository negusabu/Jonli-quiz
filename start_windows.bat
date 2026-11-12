@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py server.py
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python server.py
  ) else (
    echo Python topilmadi. python.org dan o‘rnating va "Add python.exe to PATH" ni belgilang.
  )
)
pause
