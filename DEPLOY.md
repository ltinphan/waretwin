# Deployment — waretwin.tinrobotics.com

## Architecture

```
Internet → Cloudflare Tunnel (host) → waretwin-frontend:80 (React SPA)
                                  → waretwin-backend:8000 (FastAPI + WebSocket)
```

Cloudflare Tunnel (`cloudflared`) runs on the **host** and handles TLS termination.
Services join `hermes-net` (`root_hermes-net`) so the tunnel can route by container name.

## Quick start

```bash
# 1. Build and launch containers
cd /output/waretwin
docker compose up -d --build

# 2. Add tunnel route on the host
# If a tunnel already exists (same one as papers.tinrobotics.com), add a new ingress:
cloudflared tunnel route dns <tunnel-name> waretwin.tinrobotics.com

# 3. Update ~/.cloudflared/config.yml on the host — add waretwin ingress:
# ingress:
#   - hostname: waretwin.tinrobotics.com
#     service: http://waretwin-frontend:80
#   - hostname: papers.tinrobotics.com
#     service: http://robotics-hub-web:80
#   - service: http_status:404

# 4. Restart cloudflared on the host
sudo systemctl restart cloudflared
# or: cloudflared tunnel run <tunnel-name>

# 5. Verify
curl https://waretwin.tinrobotics.com/api/health
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `TWIN_CORS_ORIGINS` | `https://waretwin.tinrobotics.com` | CORS whitelist |
| `TWIN_TRUSTED_PROXIES` | `1` | Trust X-Forwarded-For |
| `VITE_WS_URL` | `wss://waretwin.tinrobotics.com/ws` | WebSocket URL (baked into frontend at build time) |

To enable live AI mode, add to `docker-compose.yml` backend env:
```yaml
OPENAI_API_KEY: sk-...
```

## Auto-deploy (optional)

`docs/AUTO-DEPLOY.md` — one-time host + CI setup (webhook service, tunnel
path rule, `DEPLOY_TOKEN` secret), after which every merged push to `main`
triggers a pull + rebuild on the host automatically.
