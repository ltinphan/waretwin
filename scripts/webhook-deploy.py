#!/usr/bin/env python3
"""WareTwin auto-deploy webhook - stdlib HTTP server (systemd service).
GET /deploy with header X-Deploy-Token == $DEPLOY_TOKEN -> git pull + docker compose up -d --build.
Replaces the nc-coproc bash version: orphaned listeners on restart, phantom 403s from
read timeouts, connections racing onto stale nc sockets. stdlib only, single process.
# ponytail: one route, one token header; add routes/auth only if ever needed."""
import fcntl, http.server, os, subprocess, sys, threading, time

TOKEN = os.environ.get("DEPLOY_TOKEN", "")
PORT = int(os.environ.get("DEPLOY_PORT", "8712"))
REPO_DIR = os.environ.get("DEPLOY_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.environ.get("DEPLOY_LOG", "/var/log/waretwin-deploy.log")
LOCK = os.environ.get("DEPLOY_LOCK", "/run/waretwin-deploy.lock")

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%F %T%z')}] {msg}\n")

def authorized(path, token):
    return TOKEN != "" and path == "/deploy" and token == TOKEN

def deploy_async():
    def run():
        with open(LOCK, "w") as lf:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                log("deploy already running, skipped")
                return
            log("=== deploy start ===")
            for cmd in (["git", "pull", "--ff-only"], ["docker", "compose", "up", "-d", "--build"]):
                r = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True)
                log(f"$ {' '.join(cmd)} rc={r.returncode}" + (f"\n{r.stdout}{r.stderr}" if r.returncode else ""))
                if r.returncode:
                    log("=== deploy failed ===")
                    return
            time.sleep(5)
            r = subprocess.run(["docker", "inspect", "-f", "{{.Name}} {{.State.Status}}",
                                "waretwin-backend", "waretwin-frontend"], capture_output=True, text=True)
            log((r.stdout or r.stderr).strip())
            log("=== deploy done ===")
    threading.Thread(target=run, daemon=True).start()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        tok = self.headers.get("X-Deploy-Token", "")
        if authorized(self.path, tok):
            self.send_response(202); self.end_headers()
            log("deploy triggered")
            deploy_async()
        else:
            self.send_response(403); self.end_headers()
            log(f"rejected: {self.path}")
    def log_message(self, *a):  # keep stderr clean under systemd
        pass

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        if TOKEN:
            assert authorized("/deploy", TOKEN), "matching header token must deploy"
        assert not authorized("/deploy", ""), "empty token must not pass"
        assert not authorized("/other", "x") or TOKEN == "x", "other paths must not deploy"
        assert not authorized("/deploy?token=x", "x") or TOKEN == "x", "query-string tokens must not pass"
        print("self-test OK (set DEPLOY_TOKEN to test the live decision)")
        sys.exit(0)
    assert TOKEN, "set DEPLOY_TOKEN (via systemd Environment=... or /etc/waretwin-deploy.env)"
    log("webhook listening")
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
