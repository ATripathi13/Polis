# Docker Quick Reference

## Start Services (All 4)

### Windows
```powershell
.\docker.ps1 up
```

### macOS/Linux
```bash
./docker.sh up
```

### Manual Docker Compose
```bash
docker compose -f deployment/docker/docker-compose.yml up -d
```

## Stop Services

### Windows
```powershell
.\docker.ps1 down
```

### macOS/Linux
```bash
./docker.sh down
```

## View Logs

### Windows (live)
```powershell
.\docker.ps1 logs
```

### macOS/Linux (live)
```bash
./docker.sh logs
```

## Check Status

### Windows
```powershell
.\docker.ps1 status
```

### macOS/Linux
```bash
./docker.sh status
```

## Health Checks

### Windows
```powershell
.\docker.ps1 postgres-health     # Check PostgreSQL
.\docker.ps1 qdrant-health       # Check Qdrant
.\docker.ps1 minio-health        # Check MinIO
```

### macOS/Linux
```bash
./docker.sh postgres-health      # Check PostgreSQL
./docker.sh qdrant-health        # Check Qdrant
./docker.sh minio-health         # Check MinIO
```

## Access Databases

### PostgreSQL CLI

#### Windows
```powershell
.\docker.ps1 psql
```

#### macOS/Linux
```bash
./docker.sh psql
```

#### Direct Connection
```bash
# From host machine
psql -U polis -h localhost -d polis
# Password: polis_dev_password

# Or from Docker
docker compose -f deployment/docker/docker-compose.yml exec postgres \
  psql -U polis -d polis
```

### MinIO Console
```
http://localhost:9001
Username: minioadmin
Password: minioadmin_dev_password
```

### Qdrant API
```
http://localhost:6333
API Key: qdrant_key_dev
```

## Restart Services

### Windows
```powershell
.\docker.ps1 restart
```

### macOS/Linux
```bash
./docker.sh restart
```

## Clean Up Everything (Delete All Data)

### Windows
```powershell
.\docker.ps1 clean
```

### macOS/Linux
```bash
./docker.sh clean
```

## Service Details

### PostgreSQL
- Host: `postgres` (in Docker) / `localhost` (from host)
- Port: 5432
- Database: `polis`
- User: `polis`
- Password: `polis_dev_password`

### Qdrant
- Host: `qdrant` (in Docker) / `localhost` (from host)
- Port: 6333
- API Key: `qdrant_key_dev`

### MinIO
- API Host: `minio` (in Docker) / `localhost` (from host)
- API Port: 9000
- Console Port: 9001
- Access Key: `minioadmin`
- Secret Key: `minioadmin_dev_password`

## Docker Compose Direct Commands

### Start
```bash
docker compose -f deployment/docker/docker-compose.yml up -d
```

### Stop
```bash
docker compose -f deployment/docker/docker-compose.yml down
```

### View Logs
```bash
docker compose -f deployment/docker/docker-compose.yml logs -f
```

### Status
```bash
docker compose -f deployment/docker/docker-compose.yml ps
```

### Delete All Data
```bash
docker compose -f deployment/docker/docker-compose.yml down -v
```

## Troubleshooting

### Port Already in Use
Change the port mapping in `deployment/docker/docker-compose.yml`:
```yaml
ports:
  - "5433:5432"  # Map to different host port
```

### Service Won't Start
```bash
# Check Docker is running
docker ps

# View logs
.\docker.ps1 logs    # Windows
./docker.sh logs     # macOS/Linux

# Remove and restart
.\docker.ps1 clean
.\docker.ps1 up
```

### Can't Connect to Service
1. Verify service is running: `.\docker.ps1 status`
2. Check if service is healthy: `.\docker.ps1 postgres-health`
3. Verify port mapping: `docker port polis-postgres`

## Setup Aliases (Optional)

### Bash/Zsh (.bashrc or .zshrc)
```bash
alias docker-up='./docker.sh up'
alias docker-down='./docker.sh down'
alias docker-logs='./docker.sh logs'
alias docker-status='./docker.sh status'
alias docker-psql='./docker.sh psql'
```

Then use:
```bash
docker-up
docker-logs
docker-psql
```

### PowerShell (Profile)
```powershell
Set-Alias docker-up -Value '.\docker.ps1 up'
Set-Alias docker-down -Value '.\docker.ps1 down'
Set-Alias docker-logs -Value '.\docker.ps1 logs'
Set-Alias docker-status -Value '.\docker.ps1 status'
Set-Alias docker-psql -Value '.\docker.ps1 psql'
```

## See Also

- Full guide: [deployment/docker/README.md](../deployment/docker/README.md)
- Main docs: [docs/QUICKSTART.md](./QUICKSTART.md)
