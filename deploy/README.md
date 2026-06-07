# Deploying to a VPS (strike.perfecthold.online)

One server runs everything: nginx serves the built React frontend and reverse-proxies
`/api/*` to the FastAPI backend (uvicorn under systemd). DNS for
`strike.perfecthold.online` must already point at the VPS (A record).

## One-paste deploy

SSH in and run the bootstrap (pass your the-odds-api key inline so it lands only in the
server's env file, never in the repo):

```bash
ssh root@187.77.111.16

curl -fsSL https://raw.githubusercontent.com/mrglennc64/strike/main/deploy/bootstrap.sh \
  | ODDS_KEY=YOUR_THEODDSAPI_KEY LE_EMAIL=you@example.com bash
```

The script (idempotent — safe to re-run to update):

1. installs nginx, Python, Node 20, certbot
2. clones/pulls the repo to `/opt/strike`
3. builds the backend venv and the frontend (`VITE_API_BASE=/api`)
4. writes secrets to `/etc/mlb-edge.env` (chmod 600)
5. installs + starts the `mlb-edge` systemd service
6. installs the nginx site and reloads
7. if `LE_EMAIL` is set, issues HTTPS via Let's Encrypt

Then visit **http://strike.perfecthold.online** (landing) → **/app** (engine).

## Pieces

| File | Role |
|---|---|
| `deploy/bootstrap.sh` | full idempotent deploy/update script |
| `deploy/mlb-edge.service` | systemd unit running uvicorn on 127.0.0.1:8000 |
| `deploy/nginx-strike.conf` | nginx: static frontend + `/api/` proxy |
| `/etc/mlb-edge.env` | secrets (NOT in repo) — the odds key lives here |

## Common operations

```bash
systemctl restart mlb-edge          # after editing /etc/mlb-edge.env
journalctl -u mlb-edge -f           # backend logs
nano /etc/mlb-edge.env              # change odds key / thresholds
# redeploy latest code:
curl -fsSL https://raw.githubusercontent.com/mrglennc64/strike/main/deploy/bootstrap.sh | bash
```

## Nightly backtest (optional)

Once games complete, settle logged predictions:

```bash
cd /opt/strike/backend && .venv/bin/python -m app.backtest.run
# or add to crontab to run each morning:
# 0 9 * * * cd /opt/strike/backend && .venv/bin/python -m app.backtest.run >> /opt/strike/data/backtest.log 2>&1
```

## Security

- The odds key lives only in `/etc/mlb-edge.env` (chmod 600), never in the repo or the
  frontend bundle. Rotate the key you shared earlier.
- Consider a firewall (ufw) allowing only 22/80/443, and SSH key auth instead of password.
