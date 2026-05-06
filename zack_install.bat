@echo off
title Zack.ai — Installation
color 0A

echo.
echo  ========================================================
echo   ZACK.AI — Personalised LinkedIn Outreach Agent
echo   Installation Script
echo  ========================================================
echo.

REM Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed.
    echo  Please download Python from https://python.org
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo  [1/5] Python found. Installing required packages...
echo.

pip install selenium gspread google-auth groq requests sendgrid --break-system-packages --quiet

echo  [2/5] Packages installed.
echo.

REM Check ChromeDriver exists
if not exist "chromedriver.exe" (
    echo  [WARNING] chromedriver.exe not found in this folder.
    echo  Download it from: https://googlechromelabs.github.io/chrome-for-testing/
    echo  Match your Chrome version — check chrome://settings/help
    echo.
)

REM Check credentials file
if not exist "google_credentials.json" (
    echo  [WARNING] google_credentials.json not found.
    echo  Add your Google service account credentials file to this folder.
    echo.
)

REM Check config file
if not exist "zack_config.py" (
    echo  [WARNING] zack_config.py not found.
    echo  Your Zack configuration file should be in this folder.
    echo.
)

echo  [3/5] Setting up environment variables...

REM Read API keys from config and set them
python -c "import zack_config as c; import os; print(c.GROQ_API_KEY)" > temp_key.txt 2>nul
set /p GROQ_KEY=<temp_key.txt
del temp_key.txt 2>nul
if not "%GROQ_KEY%"=="" (
    setx GROQ_API_KEY "%GROQ_KEY%" >nul
)

echo  [4/5] Creating desktop shortcuts...

REM Create desktop shortcuts for each Zack script
set DESKTOP=%USERPROFILE%\Desktop
set ZACK_DIR=%~dp0

REM Scan shortcut
echo @echo off > "%DESKTOP%\Zack - Scan Connections.bat"
echo cd /d "%ZACK_DIR%" >> "%DESKTOP%\Zack - Scan Connections.bat"
echo python zacharia_connections.py scan >> "%DESKTOP%\Zack - Scan Connections.bat"
echo pause >> "%DESKTOP%\Zack - Scan Connections.bat"

REM Message shortcut
echo @echo off > "%DESKTOP%\Zack - Send Messages.bat"
echo cd /d "%ZACK_DIR%" >> "%DESKTOP%\Zack - Send Messages.bat"
echo python zacharia_send_messages.py >> "%DESKTOP%\Zack - Send Messages.bat"
echo pause >> "%DESKTOP%\Zack - Send Messages.bat"

REM Connections message shortcut
echo @echo off > "%DESKTOP%\Zack - Message Connections.bat"
echo cd /d "%ZACK_DIR%" >> "%DESKTOP%\Zack - Message Connections.bat"
echo python zacharia_connections.py message >> "%DESKTOP%\Zack - Message Connections.bat"
echo pause >> "%DESKTOP%\Zack - Message Connections.bat"

REM Engage shortcut
echo @echo off > "%DESKTOP%\Zack - Engage (Comments).bat"
echo cd /d "%ZACK_DIR%" >> "%DESKTOP%\Zack - Engage (Comments).bat"
echo python zacharia_engage.py >> "%DESKTOP%\Zack - Engage (Comments).bat"
echo pause >> "%DESKTOP%\Zack - Engage (Comments).bat"

echo  [5/5] Scheduling automatic runs...

REM Schedule morning and afternoon runs
schtasks /delete /tn "Zack Morning" /f >nul 2>&1
schtasks /delete /tn "Zack Afternoon" /f >nul 2>&1

schtasks /create /tn "Zack Morning" ^
  /tr "\"%ZACK_DIR%zacharia_runner.bat\"" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 07:00 /rl HIGHEST /f >nul

schtasks /create /tn "Zack Afternoon" ^
  /tr "\"%ZACK_DIR%zacharia_runner.bat\"" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 13:00 /rl HIGHEST /f >nul

echo.
echo  ========================================================
echo   INSTALLATION COMPLETE
echo  ========================================================
echo.
echo   Zack is now installed and scheduled.
echo.
echo   DESKTOP SHORTCUTS CREATED:
echo   - Zack - Scan Connections
echo   - Zack - Send Messages
echo   - Zack - Message Connections
echo   - Zack - Engage (Comments)
echo.
echo   AUTOMATIC SCHEDULE:
echo   - Weekdays at 7:00 AM
echo   - Weekdays at 1:00 PM
echo.
echo   NEXT STEPS:
echo   1. Double-click "Zack - Scan Connections" on your desktop
echo   2. Log into LinkedIn when Chrome opens
echo   3. Zack will find your connections automatically
echo   4. Run "Zack - Message Connections" to start messaging
echo.
echo   Need help? Contact your Zack.ai setup team.
echo  ========================================================
echo.
pause
