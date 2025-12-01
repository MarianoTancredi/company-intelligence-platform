@echo off
echo Starting Company Intelligence Platform...
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    echo Virtual environment created.
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Check if dependencies are installed
echo Checking dependencies...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    echo.
)

REM Check if .env file exists
if not exist ".env" (
    echo WARNING: .env file not found!
    echo The application will use mock data without API keys.
    echo Create a .env file with your API keys for full functionality.
    echo See SETUP.md for details.
    echo.
    pause
)

REM Start the application
echo Starting FastAPI server...
echo.
echo Dashboard: http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

