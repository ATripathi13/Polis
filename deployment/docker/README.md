# Docker Deployment Guide

## Overview

The Polis system uses Docker and Docker Compose to run all services in isolated containers with proper networking and persistence.

## Services

| Service | Port | Image | Purpose |
|---------|------|-------|---------|
| PostgreSQL | 5432 | postgres:16-alpine | Primary relational database |
| Qdrant | 6333 | qdrant/qdrant:latest | Vector database for embeddings |
| MinIO API | 9000 | minio/minio:latest | Object storage API |
| MinIO Console | 9001 | minio/minio:latest | MinIO web UI |

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

Verify installation:
```bash
docker --version
docker compose version
```

## Quick Start

### 1. Start All Services

From the project root:
```bash
docker compose -f deployment/docker/docker-compose.yml up -d
```

The `-d` flag runs services in detached mode (background).

### 2. Verify Services Are Running

```bash
docker compose -f deployment/docker/docker-compose.yml ps
```

Expected output:
```
NAME              COMMAND                  SERVICE     STATUS
polis-postgres    "postgres"              postgres    Up (healthy)
polis-qdrant      "/qdrant/qdrant -c..."  qdrant      Up (healthy)
polis-minio       "/usr/bin/minio serv..." minio      Up (healthy)
```

### 3. Stop All Services

```bash
docker compose -f deployment/docker/docker-compose.yml down
```

To remove volumes as well (deletes all data):
```bash
docker compose -f deployment/docker/docker-compose.yml down -v
```

## Service Details

### PostgreSQL

**Connection Details:**
- Hostname: `postgres` (in Docker network) or `localhost` (from host)
- Port: `5432`
- Database: `polis`
- User: `polis`
- Password: `polis_dev_password`

**Connection String:**
```
postgresql://polis:polis_dev_password@localhost:5432/polis
```

**Access from Host:**
```bash
psql postgresql://polis:polis_dev_password@localhost:5432/polis
```

**Access from Docker Container:**
```bash
docker compose -f deployment/docker/docker-compose.yml exec postgres psql -U polis -d polis
```

**Data Persistence:**
- Volume: `postgres_data`
- Location: Docker managed volume
- Survives container restart

### Qdrant

**Connection Details:**
- Hostname: `qdrant` (in Docker network) or `localhost` (from host)
- Port: `6333`
- API Key: `qdrant_key_dev`

**API Endpoint:**
```
http://localhost:6333
```

**Check Health:**
```bash
curl http://localhost:6333/health
```

**Collections API:**
```bash
curl http://localhost:6333/collections \
  -H "api-key: qdrant_key_dev"
```

**Data Persistence:**
- Volume: `qdrant_data`
- Location: Docker managed volume
- Survives container restart

### MinIO

**MinIO API:**
- Hostname: `minio` (in Docker network) or `localhost` (from host)
- Port: `9000`
- Access Key: `minioadmin`
- Secret Key: `minioadmin_dev_password`

**MinIO Console (Web UI):**
- URL: `http://localhost:9001`
- Username: `minioadmin`
- Password: `minioadmin_dev_password`

**Connection String (S3 Compatible):**
```
s3://minioadmin:minioadmin_dev_password@minio:9000
```

**Create Bucket via CLI:**
```bash
docker compose -f deployment/docker/docker-compose.yml exec minio \
  mc mb minio/polis
```

**Check Health:**
```bash
curl http://localhost:9000/minio/health/live
```

**Data Persistence:**
- Volume: `minio_data`
- Location: Docker managed volume
- Survives container restart

## Docker Network

All services connect via a bridge network `polis_network`. This allows:
- Services to reach each other by service name
- Example: PostgreSQL accessible as `postgres:5432` from other containers
- Services isolated from host network except on published ports

## Logs

### View All Logs

```bash
docker compose -f deployment/docker/docker-compose.yml logs
```

### Follow Logs in Real-Time

```bash
docker compose -f deployment/docker/docker-compose.yml logs -f
```

### View Logs for Specific Service

```bash
# PostgreSQL
docker compose -f deployment/docker/docker-compose.yml logs postgres

# Qdrant
docker compose -f deployment/docker/docker-compose.yml logs qdrant

# MinIO
docker compose -f deployment/docker/docker-compose.yml logs minio
```

## Configuration

### Environment Variables

Docker services use environment variables from `.env.docker`:
- Database URL points to `postgres` service
- Vector store URL points to `qdrant` service
- MinIO endpoint points to `minio` service

All hostnames resolve within the Docker network.

### Updating Configuration

1. Edit `.env.docker`
2. Restart services:
   ```bash
   docker compose -f deployment/docker/docker-compose.yml down
   docker compose -f deployment/docker/docker-compose.yml up -d
   ```

## Volumes

Persistent data is stored in Docker volumes:

### List Volumes

```bash
docker volume ls | grep polis
```

### Inspect Volume

```bash
docker volume inspect polis_postgres_data
docker volume inspect polis_qdrant_data
docker volume inspect polis_minio_data
```

### Backup Volumes

```bash
# Backup PostgreSQL
docker run --rm -v polis_postgres_data:/data \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/postgres-backup.tar.gz -C /data .

# Backup Qdrant
docker run --rm -v polis_qdrant_data:/data \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/qdrant-backup.tar.gz -C /data .

# Backup MinIO
docker run --rm -v polis_minio_data:/data \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/minio-backup.tar.gz -C /data .
```

## Health Checks

Each service has health checks configured:

```bash
# Check service health
docker compose -f deployment/docker/docker-compose.yml ps

# Manual health check
curl http://localhost:6333/health      # Qdrant
curl http://localhost:9000/minio/health/live  # MinIO
```

Services are considered healthy when:
- PostgreSQL: `pg_isready` command succeeds
- Qdrant: `/health` endpoint responds
- MinIO: `/minio/health/live` endpoint responds

## Troubleshooting

### Service Won't Start

```bash
# Check logs
docker compose -f deployment/docker/docker-compose.yml logs postgres

# Restart service
docker compose -f deployment/docker/docker-compose.yml restart postgres
```

### Port Already in Use

If a port is already in use, either:
1. Stop the service using the port
2. Change the port mapping in `docker-compose.yml`:
   ```yaml
   ports:
     - "5433:5432"  # Map to different host port
   ```

### Connection Issues

From within Docker container:
```bash
# Test PostgreSQL connection
docker compose -f deployment/docker/docker-compose.yml exec postgres \
  pg_isready -h postgres

# Test Qdrant connection
docker compose -f deployment/docker/docker-compose.yml exec qdrant \
  curl http://qdrant:6333/health

# Test MinIO connection
docker compose -f deployment/docker/docker-compose.yml exec minio \
  curl http://minio:9000/minio/health/live
```

### Reset Everything

```bash
# Stop and remove all containers, networks, volumes
docker compose -f deployment/docker/docker-compose.yml down -v

# Remove images
docker image prune

# Start fresh
docker compose -f deployment/docker/docker-compose.yml up -d
```

## Development Workflow

### Running with Application Code

1. **Build Application Image:**
   ```bash
   docker build -f deployment/docker/Dockerfile -t polis:dev .
   ```

2. **Add to docker-compose.yml:**
   ```yaml
   polis:
     build:
       context: .
       dockerfile: deployment/docker/Dockerfile
     container_name: polis-app
     ports:
       - "8000:8000"
     depends_on:
       postgres:
         condition: service_healthy
       qdrant:
         condition: service_healthy
       minio:
         condition: service_healthy
     environment:
       DATABASE_URL: postgresql://polis:polis_dev_password@postgres:5432/polis
       VECTOR_STORE_URL: http://qdrant:6333
     networks:
       - polis_network
   ```

3. **Run All Services:**
   ```bash
   docker compose -f deployment/docker/docker-compose.yml up -d
   ```

### Local Development (No Docker)

For local Python development without Docker:

1. Copy environment file:
   ```bash
   cp .env.example .env
   ```

2. Update `.env` for local services:
   ```
   DATABASE_URL=postgresql://polis:polis_dev_password@localhost:5432/polis
   VECTOR_STORE_URL=http://localhost:6333
   ```

3. Run infrastructure only:
   ```bash
   docker compose -f deployment/docker/docker-compose.yml up -d
   ```

4. Run application locally:
   ```bash
   python -m uvicorn apps.api.main:app --reload
   ```

## Production Considerations

- Change all default passwords in `.env.docker`
- Use persistent volumes or cloud storage
- Set `DEBUG=false` and `ENVIRONMENT=production`
- Use environment-specific docker-compose files
- Implement backup strategy
- Monitor service health and logs
- Use resource limits for containers
- Implement proper secrets management

## Shortcuts

Create shell functions in your `.bashrc` or `.zshrc`:

```bash
# Start services
alias polis-up='docker compose -f deployment/docker/docker-compose.yml up -d'

# Stop services
alias polis-down='docker compose -f deployment/docker/docker-compose.yml down'

# View logs
alias polis-logs='docker compose -f deployment/docker/docker-compose.yml logs -f'

# Check status
alias polis-status='docker compose -f deployment/docker/docker-compose.yml ps'

# Access PostgreSQL
alias polis-psql='docker compose -f deployment/docker/docker-compose.yml exec postgres psql -U polis -d polis'
```

Then use:
```bash
polis-up
polis-status
polis-logs
polis-down
```

## See Also

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [PostgreSQL Docker Image](https://hub.docker.com/_/postgres)
- [Qdrant Docker Image](https://hub.docker.com/r/qdrant/qdrant)
- [MinIO Docker Image](https://hub.docker.com/r/minio/minio)
