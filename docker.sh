#!/bin/bash
# Polis Docker Management Script
# Usage: ./docker.sh [command]

set -e

COMPOSE_FILE="deployment/docker/docker-compose.yml"
ENV_FILE="deployment/docker/.env.docker"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${GREEN}=== Polis Docker Management ===${NC}"
}

print_error() {
    echo -e "${RED}✗ Error: $1${NC}"
    exit 1
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Check if docker and docker-compose are installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
    fi
    
    if ! command -v docker compose &> /dev/null; then
        print_error "Docker Compose is not installed. Please install Docker Compose first."
    fi
}

# Show help
show_help() {
    print_header
    echo ""
    echo "Available commands:"
    echo "  up              Start all services in background"
    echo "  down            Stop all services"
    echo "  restart         Restart all services"
    echo "  status          Show service status"
    echo "  logs            Follow service logs"
    echo "  ps              List running services"
    echo "  psql            Open PostgreSQL CLI"
    echo "  qdrant-health   Check Qdrant health"
    echo "  minio-health    Check MinIO health"
    echo "  postgres-health Check PostgreSQL health"
    echo "  clean           Stop services and remove volumes (deletes data!)"
    echo "  help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./docker.sh up              # Start all services"
    echo "  ./docker.sh logs            # View live logs"
    echo "  ./docker.sh psql            # Access PostgreSQL"
    echo "  ./docker.sh clean           # Remove everything"
}

# Start services
start_services() {
    print_header
    print_info "Starting Polis services..."
    docker compose -f "$COMPOSE_FILE" up -d
    print_success "All services started"
    echo ""
    status_services
}

# Stop services
stop_services() {
    print_header
    print_info "Stopping Polis services..."
    docker compose -f "$COMPOSE_FILE" down
    print_success "All services stopped"
}

# Restart services
restart_services() {
    print_header
    print_info "Restarting Polis services..."
    docker compose -f "$COMPOSE_FILE" restart
    print_success "All services restarted"
    echo ""
    status_services
}

# Show status
status_services() {
    print_info "Service Status:"
    docker compose -f "$COMPOSE_FILE" ps
}

# Show logs
show_logs() {
    print_header
    print_info "Following service logs (Ctrl+C to stop)..."
    docker compose -f "$COMPOSE_FILE" logs -f
}

# List services
list_services() {
    docker compose -f "$COMPOSE_FILE" ps
}

# PostgreSQL CLI
open_psql() {
    print_header
    print_info "Opening PostgreSQL CLI..."
    docker compose -f "$COMPOSE_FILE" exec postgres \
        psql -U polis -d polis
}

# Check Qdrant health
check_qdrant() {
    print_header
    print_info "Checking Qdrant health..."
    RESPONSE=$(curl -s http://localhost:6333/health || echo "{}")
    
    if [[ $RESPONSE == *"ok"* ]]; then
        print_success "Qdrant is healthy"
        echo "$RESPONSE" | jq . 2>/dev/null || echo "$RESPONSE"
    else
        print_error "Qdrant is not responding. Is it running? (docker.sh up)"
    fi
}

# Check MinIO health
check_minio() {
    print_header
    print_info "Checking MinIO health..."
    RESPONSE=$(curl -s http://localhost:9000/minio/health/live)
    
    if [ $? -eq 0 ]; then
        print_success "MinIO is healthy"
        echo "MinIO API: http://localhost:9000"
        echo "MinIO Console: http://localhost:9001"
        echo "Username: minioadmin"
        echo "Password: minioadmin_dev_password"
    else
        print_error "MinIO is not responding. Is it running? (docker.sh up)"
    fi
}

# Check PostgreSQL health
check_postgres() {
    print_header
    print_info "Checking PostgreSQL health..."
    
    RESPONSE=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
        pg_isready -U polis -d polis 2>&1 || echo "failed")
    
    if [[ $RESPONSE == *"accepting connections"* ]]; then
        print_success "PostgreSQL is healthy"
        echo "Connection: psql -U polis -h localhost -d polis"
        echo "Password: polis_dev_password"
    else
        print_error "PostgreSQL is not responding. Is it running? (docker.sh up)"
    fi
}

# Clean up everything
clean_all() {
    print_header
    read -p "This will delete ALL data (volumes). Are you sure? (yes/no): " -r
    echo
    if [[ $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        print_info "Removing all services and volumes..."
        docker compose -f "$COMPOSE_FILE" down -v
        print_success "All services and data removed"
    else
        print_info "Cancelled"
    fi
}

# Main
main() {
    check_docker
    
    case "${1:-help}" in
        up)
            start_services
            ;;
        down)
            stop_services
            ;;
        restart)
            restart_services
            ;;
        status)
            status_services
            ;;
        logs)
            show_logs
            ;;
        ps)
            list_services
            ;;
        psql)
            open_psql
            ;;
        qdrant-health)
            check_qdrant
            ;;
        minio-health)
            check_minio
            ;;
        postgres-health)
            check_postgres
            ;;
        clean)
            clean_all
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
