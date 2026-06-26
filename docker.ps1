# Polis Docker Management Script for Windows
# Usage: .\docker.ps1 [command]

param(
    [string]$Command = "help"
)

$COMPOSE_FILE = "deployment\docker\docker-compose.yml"
$ENV_FILE = "deployment\docker\.env.docker"

# Color output
function Write-Header {
    Write-Host "=== Polis Docker Management ===" -ForegroundColor Green
}

function Write-Error {
    Write-Host "✗ Error: $args" -ForegroundColor Red
    exit 1
}

function Write-Success {
    Write-Host "✓ $args" -ForegroundColor Green
}

function Write-Info {
    Write-Host "ℹ $args" -ForegroundColor Yellow
}

# Check if docker is installed
function Test-Docker {
    try {
        $null = docker version 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Docker is not running. Please start Docker Desktop."
        }
    }
    catch {
        Write-Error "Docker is not installed. Please install Docker Desktop first."
    }
}

# Show help
function Show-Help {
    Write-Header
    Write-Host ""
    Write-Host "Available commands:"
    Write-Host "  up              Start all services in background"
    Write-Host "  down            Stop all services"
    Write-Host "  restart         Restart all services"
    Write-Host "  status          Show service status"
    Write-Host "  logs            Follow service logs"
    Write-Host "  ps              List running services"
    Write-Host "  psql            Open PostgreSQL CLI"
    Write-Host "  qdrant-health   Check Qdrant health"
    Write-Host "  minio-health    Check MinIO health"
    Write-Host "  postgres-health Check PostgreSQL health"
    Write-Host "  clean           Stop services and remove volumes (deletes data!)"
    Write-Host "  help            Show this help message"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\docker.ps1 up              # Start all services"
    Write-Host "  .\docker.ps1 logs            # View live logs"
    Write-Host "  .\docker.ps1 psql            # Access PostgreSQL"
    Write-Host "  .\docker.ps1 clean           # Remove everything"
}

# Start services
function Start-Services {
    Write-Header
    Write-Info "Starting Polis services..."
    docker compose -f $COMPOSE_FILE up -d
    Write-Success "All services started"
    Write-Host ""
    Get-Status
}

# Stop services
function Stop-Services {
    Write-Header
    Write-Info "Stopping Polis services..."
    docker compose -f $COMPOSE_FILE down
    Write-Success "All services stopped"
}

# Restart services
function Restart-Services {
    Write-Header
    Write-Info "Restarting Polis services..."
    docker compose -f $COMPOSE_FILE restart
    Write-Success "All services restarted"
    Write-Host ""
    Get-Status
}

# Get status
function Get-Status {
    Write-Info "Service Status:"
    docker compose -f $COMPOSE_FILE ps
}

# Show logs
function Show-Logs {
    Write-Header
    Write-Info "Following service logs (Ctrl+C to stop)..."
    docker compose -f $COMPOSE_FILE logs -f
}

# List services
function List-Services {
    docker compose -f $COMPOSE_FILE ps
}

# Open PostgreSQL CLI
function Open-PostgreSQL {
    Write-Header
    Write-Info "Opening PostgreSQL CLI..."
    docker compose -f $COMPOSE_FILE exec postgres `
        psql -U polis -d polis
}

# Check Qdrant health
function Test-Qdrant {
    Write-Header
    Write-Info "Checking Qdrant health..."
    try {
        $Response = Invoke-WebRequest -Uri "http://localhost:6333/health" -ErrorAction Stop
        Write-Success "Qdrant is healthy"
        Write-Host $Response.Content
    }
    catch {
        Write-Error "Qdrant is not responding. Is it running? (.\docker.ps1 up)"
    }
}

# Check MinIO health
function Test-MinIO {
    Write-Header
    Write-Info "Checking MinIO health..."
    try {
        $Response = Invoke-WebRequest -Uri "http://localhost:9000/minio/health/live" -ErrorAction Stop
        Write-Success "MinIO is healthy"
        Write-Host "MinIO API: http://localhost:9000"
        Write-Host "MinIO Console: http://localhost:9001"
        Write-Host "Username: minioadmin"
        Write-Host "Password: minioadmin_dev_password"
    }
    catch {
        Write-Error "MinIO is not responding. Is it running? (.\docker.ps1 up)"
    }
}

# Check PostgreSQL health
function Test-PostgreSQL {
    Write-Header
    Write-Info "Checking PostgreSQL health..."
    try {
        $null = docker compose -f $COMPOSE_FILE exec -T postgres `
            pg_isready -U polis -d polis 2>$null
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "PostgreSQL is healthy"
            Write-Host "Connection: psql -U polis -h localhost -d polis"
            Write-Host "Password: polis_dev_password"
        }
        else {
            Write-Error "PostgreSQL is not responding. Is it running? (.\docker.ps1 up)"
        }
    }
    catch {
        Write-Error "PostgreSQL is not responding. Is it running? (.\docker.ps1 up)"
    }
}

# Clean up everything
function Clean-All {
    Write-Header
    $Response = Read-Host "This will delete ALL data (volumes). Are you sure? (yes/no)"
    
    if ($Response -eq "yes") {
        Write-Info "Removing all services and volumes..."
        docker compose -f $COMPOSE_FILE down -v
        Write-Success "All services and data removed"
    }
    else {
        Write-Info "Cancelled"
    }
}

# Main
Test-Docker

switch ($Command.ToLower()) {
    "up" { Start-Services }
    "down" { Stop-Services }
    "restart" { Restart-Services }
    "status" { Get-Status }
    "logs" { Show-Logs }
    "ps" { List-Services }
    "psql" { Open-PostgreSQL }
    "qdrant-health" { Test-Qdrant }
    "minio-health" { Test-MinIO }
    "postgres-health" { Test-PostgreSQL }
    "clean" { Clean-All }
    "help" { Show-Help }
    default {
        Write-Error "Unknown command: $Command"
        Show-Help
        exit 1
    }
}
