@echo off
title Zack.ai — Commenting Agent Installation
color 0A

echo.
echo  ========================================================
echo   ZACK.AI — LinkedIn Commenting Agent
echo   Installation
echo  ========================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed or not on PATH.
    echo.
    echo  Run this command to install Python:
    echo.
    echo      winget install Python.Python.3.12
    echo.
    echo  Then close this window, open a new Command Prompt,
    echo  and run zack_install.bat again.
    echo.
    pause
    exit /b 1
)

echo  [1/4] Python found.
echo.

REM Install required packages
echo  [2/4] Installing required packages...
echo.
pip install selenium gspread google-auth groq requests --quiet
if errorlevel 1 (
    echo.
    echo  [ERROR] Package installation failed.
    echo  Try running this manually:
    echo.
    echo      pip install selenium gspread google-auth groq requests
    echo.
    pause
    exit /b 1
)
echo  Packages installed.
echo.

REM Check for required files
echo  [3/4] Checking required files...
echo.

if not exist "zack_config.py" (
    echo  [WARNING] zack_config.py not found.
    echo  Run: python zack_setup.py
    echo  This creates your personalised config file.
    echo.
)

if not exist "google_credentials.json" (
    echo  [WARNING] google_credentials.json not found.
    echo  Download it from the link in your access email.
    echo  Place it in this folder alongside the other files.
    echo.
)

if not exist "chromedriver.exe" (
    echo  [WARNING] chromedriver.exe not found.
    echo  1. Open Chrome and go to: chrome://settings/help
    echo  2. Note your version number e.g. 147
    echo  3. Download matching ChromeDriver from:
    echo     https://googlechromelabs.github.io/chrome-for-testing
    echo  4. Place chromedriver.exe in this folder.
    echo.
)

REM Create Desktop shortcut — ONLY the commenting agent
echo  [4/4] Creating desktop shortcut...

set DESKTOP=%USERPROFILE%\Desktop
set ZACK_DIR=%~dp0

echo @echo off > "%DESKTOP%\Zack - Engage (Comments).bat"
echo title Zack.ai - Commenting Agent >> "%DESKTOP%\Zack - Engage (Comments).bat"
echo cd /d "%ZACK_DIR%" >> "%DESKTOP%\Zack - Engage (Comments).bat"
echo python zacharia_engage.py >> "%DESKTOP%\Zack - Engage (Comments).bat"
echo pause >> "%DESKTOP%\Zack - Engage (Comments).bat"

REM Schedule twice-daily automatic runs
schtasks /delete /tn "Zack Morning Comments" /f >nul 2>&1
schtasks /delete /tn "Zack Afternoon Comments" /f >nul 2>&1

schtasks /create /tn "Zack Morning Comments" ^
  /tr "cmd /c cd /d \"%ZACK_DIR%\" && python zacharia_engage.py" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 07:00 /rl HIGHEST /f >nul 2>&1

schtasks /create /tn "Zack Afternoon Comments" ^
  /tr "cmd /c cd /d \"%ZACK_DIR%\" && python zacharia_engage.py" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 13:00 /rl HIGHEST /f >nul 2>&1

echo.
echo  ========================================================
echo   INSTALLATION COMPLETE
echo  ========================================================
echo.
echo   DESKTOP SHORTCUT CREATED:
echo   - Zack - Engage (Comments)
echo.
echo   AUTOMATIC SCHEDULE:
echo   - Weekdays at 7:00 AM
echo   - Weekdays at 1:00 PM
echo.
echo   NEXT STEPS:
echo   1. Make sure zack_config.py is in this folder
echo      (run python zack_setup.py if you haven't already)
echo.
echo   2. Make sure google_credentials.json is in this folder
echo.
echo   3. Make sure chromedriver.exe is in this folder
echo.
echo   4. Open your Google Sheet and add people to:
echo      "Zacharia Engagement List" tab
echo      Column A: Name
echo      Column B: LinkedIn URL
echo      Column C: Notes
echo.
echo   5. Double-click "Zack - Engage (Comments)" on your Desktop
echo      Log into LinkedIn when Chrome opens.
echo      Zack starts commenting automatically.
echo.
echo   Need help? Join the community:
echo   https://t.me/+Eyi00HuBB3Q3ZTNk
echo  ========================================================
echo.
pause
