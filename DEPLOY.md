# Deployment — waretwin.tinrobotics.com

## Prerequisites

- Docker + Docker Compose on the host
- TLS certs for `waretwin.tinrobotics.com` (Let's Encrypt or self-signed)

## Quick start

```bash
# 1. Get TLS certs
mkdir -p certs
# Option A: Let's Encrypt (on the host, with DNS pointing here)
certbot certonly --standalone -d waretwin.tinrobotics.com
cp /etc/letsencrypt/live/waretwin.tinrobotics.com/fullchain.pem certs/
cp /etc/letsencrypt/live/waretwin.tinrobotics.com/privkey.pem certs/

# Option B: self-signed (testing only)
openssl req -x509 -newkey rsa:2048 -nodes -keyout certs/privkey.pem   -out certs/fullchain.pem -days 365 -subj "/CN=waretwin.tinrobotics.com"

# 2. Build and launch
docker compose up -d --build

# 3. Verify
curl https://waretwin.tinrobotics.com/api/health
```

## Architecture

```
Internet → nginx:443 (TLS) → frontend:80 (React SPA)
                           → backend:8000 (FastAPI + WebSocket)
```

- **nginx** terminates TLS, routes `/` to frontend, `/ws` + `/api/` to backend
- **frontend** container builds the React app (Vite) and serves it via its own nginx
- **backend** container runs FastAPI (uvicorn) with the simulation engine

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `TWIN_CORS_ORIGINS` | `https://waretwin.tinrobotics.com` | CORS whitelist |
| `TWIN_TRUSTED_PROXIES` | `1` | Trust X-Forwarded-For from nginx |
| `VITE_WS_URL` | `wss://waretwin.tinrobotics.com/ws` | WebSocket URL baked into frontend |

To add an OpenAI key for live AI mode, add to `docker-compose.yml` backend env:
```yaml
OPENAI_API_KEY: sk-...
```
