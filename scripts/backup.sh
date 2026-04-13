#!/bin/bash
# Backup quotidien de la BDD SQLite (cron 3h, rétention 7 jours).
# Cf. ARCHITECTURE_FINALE.md — section Infra VPS.

BACKUP_DIR="/root/3d-factory/backend/data/backups"
DB_PATH="/root/3d-factory/backend/data/db.sqlite"
mkdir -p "$BACKUP_DIR"
cp "$DB_PATH" "$BACKUP_DIR/db_$(date +%Y%m%d_%H%M%S).sqlite"
find "$BACKUP_DIR" -name "*.sqlite" -mtime +7 -delete
