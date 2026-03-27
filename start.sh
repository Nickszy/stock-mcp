#!/bin/bash
# Quick start script for Dashboard

set -e

echo "========================================"
echo "Stock MCP Dashboard - Quick Start"
echo "========================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed."
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Error: Docker Compose is not installed."
    echo "Please install Docker Compose first: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "Step 1/4: Creating data directory..."
mkdir -p data

echo "Step 2/4: Building Docker images..."
docker-compose build

echo "Step 3/4: Starting services..."
docker-compose up -d

echo "Step 4/4: Waiting for services to be ready..."
sleep 5

# Check if services are running
if docker-compose ps | grep -q "Up"; then
    echo ""
    echo "========================================"
    echo "✓ Services started successfully!"
    echo "========================================"
    echo ""
    echo "Dashboard: http://localhost:8501"
    echo "API:       http://localhost:9898"
    echo ""
    echo "Useful commands:"
    echo "  View logs:       docker-compose logs -f"
    echo "  Stop services:   docker-compose down"
    echo "  Restart:         docker-compose restart"
    echo ""
else
    echo ""
    echo "========================================"
    echo "✗ Failed to start services"
    echo "========================================"
    echo ""
    echo "Check logs for details:"
    echo "  docker-compose logs"
    exit 1
fi
