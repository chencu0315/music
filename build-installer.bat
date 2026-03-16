@echo off
setlocal

cd /d "%~dp0"

echo [Light Audio Cutter] Start building installer...
call npm.cmd run pack:installer

if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b %errorlevel%
)

echo.
echo Build completed.
echo Installer path:
for /f "usebackq delims=" %%i in (`node -p "require('./package.json').version"`) do set APP_VERSION=%%i
echo %cd%\dist\Light Audio Cutter-Setup-%APP_VERSION%.exe
pause
