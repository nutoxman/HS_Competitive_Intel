# HS Tracker systemd timers

1. Copy service and timer files from this folder to `/etc/systemd/system/`.
2. Replace placeholders:
   - `<CODEX_REPO>`
   - `<PYTHON_BIN>` (example: `/opt/hs-tracker/.venv/bin/python`)
   - `<SERVICE_USER>` and `<SERVICE_GROUP>`
3. Reload systemd and enable timers:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hs-ctgov-refresh.timer
sudo systemctl enable --now hs-source-scan.timer
sudo systemctl enable --now hs-deck-scan.timer
```

4. Verify next run times:

```bash
systemctl list-timers --all | rg 'hs-(ctgov-refresh|source-scan|deck-scan)'
```
