# Server files

What runs on the server besides the code. None of it installs itself: each file is put in place by hand, as root.

| File | Goes to | What it does |
|---|---|---|
| `gitv-deploy` | `/usr/local/bin/gitv-deploy` (root:root 755) | Takes a new version from CI. Runs new migrations itself, with the site stopped and a copy of the database taken first. |
| `gitv-backup` | `/usr/local/bin/gitv-backup` (root:root 755) | A checked, compressed copy of the database in `/opt/gitv/backups`, kept 14 days. |
| `gitv-backup.service`, `gitv-backup.timer` | `/etc/systemd/system/` | Run it every night. |
| `gitv-worker.service` | `/etc/systemd/system/` | The background sync, live poll and stream as a process of their own, below the API in priority. |
| `gitv-api-no-sync.conf` | `/etc/systemd/system/gitv-api.service.d/no-sync.conf` | Tells the API to leave that work to the worker. |

## Backups

```bash
install -o root -g root -m 755 gitv-backup /usr/local/bin/gitv-backup
install -m 644 gitv-backup.service gitv-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gitv-backup.timer
systemctl start gitv-backup.service && journalctl -u gitv-backup -n 5 --no-pager
```

The copies stay on the server, so a lost disk loses them too. Fetch the latest one somewhere else from time to time
(or on a schedule), for example `rsync -a <server>:/opt/gitv/backups/ ~/gitv-backups/`.

To bring one back: stop `gitv-api` and `gitv-worker`, `gunzip` the copy, remove `gitv.db-wal` and `gitv.db-shm`,
put the copy in place of `/opt/gitv/app/api/gitv.db` (owner `gitv`), start the services.

## The worker

Both steps together: with only the first the background work stops, with only the second it's done twice.

```bash
install -D -m 644 gitv-api-no-sync.conf /etc/systemd/system/gitv-api.service.d/no-sync.conf
install -m 644 gitv-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl restart gitv-api
systemctl enable --now gitv-worker
journalctl -u gitv-worker -n 20 --no-pager
```

Needs the code with `python -m app.cli worker` on the server first. To go back: `systemctl disable --now gitv-worker`,
remove `no-sync.conf`, `systemctl daemon-reload`, `systemctl restart gitv-api`.

## The deploy script

```bash
install -o root -g root -m 755 gitv-deploy /usr/local/bin/gitv-deploy
```

A change to it in the repository does nothing until it's installed like this.
