#!/usr/bin/env bash
set -euo pipefail

# ===========================================
# WareTwin — Deploy via Cloudflare Tunnel
# ===========================================
# Run on the host: ./scripts/deploy.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}🚀 Deploying WareTwin...${NC}"
cd "$PROJECT_DIR"

# 1. Check Docker
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker daemon is not running. Start Docker and try again.${NC}"
    exit 1
fi

# 2. Build + start services
echo -e "${YELLOW}📦 Building and starting Docker services...${NC}"
docker compose up -d --build

# 3. Verify
echo -e "${YELLOW}⌛ Waiting for services...${NC}"
sleep 5

BACKEND_STATUS=$(docker inspect -f '{{.State.Status}}' waretwin-backend 2>/dev/null || echo "not_found")
FRONTEND_STATUS=$(docker inspect -f '{{.State.Status}}' waretwin-frontend 2>/dev/null || echo "not_found")

if [ "$BACKEND_STATUS" = "running" ]; then
    echo -e "${GREEN}✅ Backend (FastAPI) is running.${NC}"
else
    echo -e "${RED}❌ Backend failed. Check: docker logs waretwin-backend${NC}"
    exit 1
fi

if [ "$FRONTEND_STATUS" = "running" ]; then
    echo -e "${GREEN}✅ Frontend (React SPA) is running.${NC}"
else
    echo -e "${RED}❌ Frontend failed. Check: docker logs waretwin-frontend${NC}"
    exit 1
fi

# 4. Health check
echo -e "${YELLOW}🔍 Health check...${NC}"
sleep 2
if docker exec waretwin-frontend wget -qO- http://waretwin-backend:8000/api/health 2>/dev/null; then
    echo -e "${GREEN}✅ Backend health check passed.${NC}"
else
    echo -e "${YELLOW}⚠️ Health check not ready yet. Check: docker exec waretwin-frontend wget -qO- http://waretwin-backend:8000/api/health${NC}"
fi

echo ""
echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}🎉 WareTwin deployed!${NC}"
echo -e "${GREEN}=================================================${NC}"
echo ""
echo -e "  Local:  http://waretwin-frontend (via docker network)"
echo -e "  Public: https://waretwin.tinrobotics.com"
echo ""
echo -e "${YELLOW}Cloudflare Tunnel setup (on host):${NC}"
echo -e "  Add to ~/.cloudflared/config.yml:"
echo -e "    - hostname: waretwin.tinrobotics.com"
echo -e "      service: http://waretwin-frontend:80"
echo -e "  Then: sudo systemctl restart cloudflared"
echo ""
echo -e "${YELLOW}Useful:${NC}"
echo -e "  docker compose logs -f frontend   # Frontend logs"
echo -e "  docker compose logs -f backend    # Backend logs"
echo -e "  docker compose down               # Stop all"
