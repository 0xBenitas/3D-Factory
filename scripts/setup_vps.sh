#!/bin/bash
# Setup initial du VPS Hetzner CX22 (Ubuntu 24.04).
# Cf. ARCHITECTURE_FINALE.md — section Infra VPS.
# À exécuter UNE fois après provisioning.
set -e

apt update && apt upgrade -y
apt install -y python3-pip python3-venv python3-dev nodejs npm git curl

# Caddy — reverse proxy HTTPS auto (obligatoire pour auth sécurisée)
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install caddy

# Deps pyrender (rendu screenshots sans GPU)
apt install -y libosmesa6-dev freeglut3-dev

# Variable d'environnement obligatoire pour pyrender headless
echo 'export PYOPENGL_PLATFORM=osmesa' >> /root/.bashrc

# Caddy config — changer le domaine
cat > /etc/caddy/Caddyfile << 'EOF'
factory.mondomaine.com {
    reverse_proxy localhost:8000
}
EOF
systemctl restart caddy

# Backup cron
echo "0 3 * * * /root/3d-factory/scripts/backup.sh" | crontab -

echo "✅ VPS prêt"
