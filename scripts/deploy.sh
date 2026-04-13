#!/bin/bash
# Pull, build frontend, install deps, restart uvicorn.
# Cf. ARCHITECTURE_FINALE.md — section Infra VPS.
set -e
cd /root/3d-factory

git pull origin main

cd frontend && npm install && npm run build && cd ..

cd backend
source venv/bin/activate 2>/dev/null || (python3 -m venv venv && source venv/bin/activate)
pip install -r requirements.txt

pkill -f "uvicorn main:app" || true
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/3d-factory.log 2>&1 &

echo "✅ Deployed → https://factory.mondomaine.com"
