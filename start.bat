@echo off
REM Quick start script for Dashboard (Windows)

echo ========================================
echo Stock MCP Dashboard - Quick Start
echo ========================================
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if errorlevel 1 (
    echo Error: Docker is not installed.
    echo Please install Docker Desktop first: https://docs.docker.com/desktop/install/windows-install/
    exit /b 1
)

REM Check if Docker Compose is installed
docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo Error: Docker Compose is not installed.
    echo Please install Docker Desktop first: https://docs.docker.com/desktop/install/windows-install/
    exit /b 1
)

echo Step 1/4: Creating data directory...
if not exist "data" mkdir data

echo Step 2/4: Building Docker images...
docker-compose build
if errorlevel 1 (
    echo Error: Failed to build Docker images
    exit /b 1
)

echo Step 3/4: Starting services...
docker-compose up -d
if errorlevel 1 (
    echo Error: Failed to start services
    exit /b 1
)

echo Step 4/4: Waiting for services to be ready...
timeout /t 5 /nobreak >nul

REM Check if services are running
docker-compose ps | find "Up" >nul
if errorlevel 1 (
    echo.
    echo ========================================
    echo X Failed to start services
    echo ========================================
    echo.
    echo Check logs for details:
    echo   docker-compose logs
    exit /b 1
) else (
    echo.
    echo ========================================
    echo ✓ Services started successfully!
    echo ========================================
    echo.
    echo Dashboard: http://localhost:8501
    echo API:       http://localhost:9898
    echo.
    echo Useful commands:
    echo   View logs:       docker-compose logs -f
    echo   Stop services:   docker-compose down
    echo   Restart:         docker-compose restart
    echo.
)

pause
