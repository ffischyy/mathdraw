@echo off
rem ===========================================================================
rem  Build the Windows installer:  dist\installer\<AppName>-Setup-<version>.exe
rem  Needs: Python 3.11 or 3.12 (64-bit)  and  Inno Setup 6 (https://jrsoftware.org/isdl.php)
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist .venv-build (
  echo [1/8] Creating build environment...
  py -3.12 -m venv .venv-build 2>nul || py -3.11 -m venv .venv-build 2>nul || python -m venv .venv-build || goto :err
)
call .venv-build\Scripts\activate.bat || goto :err

echo [2/8] Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt -r packaging\requirements-build.txt || goto :err

echo [3/8] Fetching the hand-tracking model...
python tools\fetch_model.py || goto :err

echo [4/8] Running automated tests...
python -m pytest -q || goto :err

echo [5/8] Collecting third-party licences...
python tools\collect_licenses.py || goto :err

for /f "delims=" %%v in ('python -c "import mathdraw.branding as b;print(b.APP_NAME)"') do set APPNAME=%%v
for /f "delims=" %%v in ('python -c "import mathdraw.branding as b;print(b.APP_ID)"') do set APPID=%%v
for /f "delims=" %%v in ('python -c "import mathdraw.branding as b;print(b.VERSION)"') do set APPVER=%%v
for /f "delims=" %%v in ('python -c "import mathdraw.branding as b;print(b.PUBLISHER)"') do set PUBLISHER=%%v
for /f "delims=" %%v in ('python -c "import mathdraw.branding as b;print(b.WEBSITE)"') do set WEBSITE=%%v
if not exist mathdraw\license_pubkey.txt (
  echo.
  echo  NOTE: no licence public key found - this build will run WITHOUT a trial or licence check.
  echo        Run  python tools\make_signing_keys.py  once before building a version you sell.
  echo.
)

echo [6/8] Building %APPNAME% %APPVER% with PyInstaller...
pyinstaller packaging\mathdraw.spec --noconfirm --clean --distpath dist --workpath build\pyi || goto :err

echo [7/8] Self-test of the built app...
start "" /wait "dist\%APPNAME%\%APPNAME%.exe" --selftest
set ST=!errorlevel!
type "%LOCALAPPDATA%\%APPID%\selftest.txt"
if not "!ST!"=="0" goto :err

rem Optional code signing of the app exe (see SELLING.md), e.g.:
rem signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /a "dist\%APPNAME%\%APPNAME%.exe"

echo [8/8] Building installer...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php and run build.bat again.
  echo The unpacked app is ready in dist\%APPNAME%\
  goto :end
)
%ISCC% /DAppName="%APPNAME%" /DAppVersion="%APPVER%" /DPublisher="%PUBLISHER%" /DWebsite="%WEBSITE%" packaging\installer.iss || goto :err
echo.
echo Done:  dist\installer\%APPNAME%-Setup-%APPVER%.exe
goto :end

:err
echo.
echo BUILD FAILED - see the messages above.
:end
pause
