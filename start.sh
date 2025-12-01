#!/bin/bash

echo "Starting Company Intelligence Platform..."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "Virtual environment created."
    echo ""
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check if dependencies are installed
echo "Checking dependencies..."
if ! pip show fastapi > /dev/null 2>&1; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
    echo ""
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "WARNING: .env file not found!"
    echo "The application will use mock data without API keys."
    echo "Create a .env file with your API keys for full functionality."
    echo "See SETUP.md for details."
    echo ""
    read -p "Press enter to continue..."
fi

# Start the application
echo "Starting FastAPI server..."
echo ""
echo "Dashboard: http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
echo ""
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000


