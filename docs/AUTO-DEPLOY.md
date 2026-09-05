# Auto-deploy — waretwin.tinrobotics.com

Deploy = `git push`. A GitHub Actions deploy job calls a webhook on the host,
which pulls and rebuilds.

```
git push origin main
  -> GitHub Actions CI (tests)
  -> deploy job: curl https://waretwin.tinrobotics.com/deploy?token=...
       -> Cloudflare Tunnel (path rule ^/deploy$)
            -> host webhook (nc, port 8712)
                 -> git pull --ff-only + docker compose up -d --build
```

## One-time host setup (2 minutes)

1. Start the webhook:

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

2. Add the Cloudflare Tunnel ingress (before the `http_status:404` catchall).
   `/deploy` goes to the webhook on the host; everything else to the frontend:

```yaml
  - hostname: waretwin.tinrobotics.com
    path: ^/deploy$
    service: http://localhost:8712
  - hostname: waretwin.tinrobotics.com
    service: http://waretwin-frontend:80
```

```bash
cloudflared tunnel route dns <tunnel-name> waretwin.tinrobotics.com
sudo systemctl restart cloudflared
```

3. Add the repo secret so CI can call the webhook:
   GitHub repo Settings -> Secrets and variables -> Actions -> `DEPLOY_TOKEN` = the same token.

## Deploy

```bash
git push origin main        # CI green -> webhook -> host pulls + rebuilds
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

- Webhook binds 0.0.0.0:8712; the token is the only auth — keep it private, firewall external access to the port (Cloudflare Tunnel reaches it via localhost).
- The webhook sends `202 Accepted` and returns; the rebuild runs in the background (see logs). Overlapping triggers are skipped via `flock`.
- `docker compose up -d --build` rebuilds both containers in place; WS clients reconnect.
- Optional: `OPENAI_API_KEY` in backend env (docker-compose or backend/.env) enables the live-AI endpoints; app runs fine without it.
