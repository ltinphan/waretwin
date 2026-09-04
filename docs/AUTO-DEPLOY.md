# Auto-deploy — waretwin.tinrobotics.com

Deploy = `git push`. A tiny webhook on the host pulls and rebuilds.

## One-time host setup (2 minutes)

1. Copy the script + unit from the repo (or paste from here):

```bash
cd /output/waretwin
git pull
sudo cp scripts/waretwin-deploy.service /etc/systemd/system/
# set your token:
sudo systemctl edit waretwin-deploy --stdin << 'UNIT'
[Service]
Environment=DEPLOY_TOKEN=<random-string>
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now waretwin-deploy
```

2. Add the Cloudflare Tunnel ingress (before the `http_status:404` catchall):

```yaml
  - hostname: waretwin.tinrobotics.com
    service: http://waretwin-frontend:80
```

```bash
cloudflared tunnel route dns <tunnel-name> waretwin.tinrobotics.com
sudo systemctl restart cloudflared
```

## Deploy

From anywhere with push access:

```bash
git push origin main        # host pulls + rebuilds automatically
```

Or manually on the host:

```bash
curl "http://localhost:8712/deploy?token=<DEPLOY_TOKEN>"
# or: cd /output/waretwin && docker compose up -d --build
```

## Logs

```bash
tail -f /var/log/waretwin-deploy.log
```

## Notes

- Webhook binds 0.0.0.0:8712; the token is the only auth — keep it private, firewall external access to the port.
- `docker compose up -d --build` rebuilds both containers in place; WS clients reconnect.
- Optional: `OPENAI_API_KEY` in backend env (docker-compose or backend/.env) enables the live-AI endpoints; app runs fine without it.
