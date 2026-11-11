#!/usr/bin/env python3
"""Выгрузка Эло игроков до каждого матча (elo_before.csv), которую читает model.py.

ВНИМАНИЕ: запускать только на КОПИИ базы, не на боевой gitv.db. Код приложения при подключении меняет базу
(например, включает режим WAL в api/app/database.py), поэтому на копии сначала нужен `alembic upgrade head`
(из папки api/). Скрипт использует настройки приложения (api/.env или переменные окружения: secret_key и
остальные обязательные поля), поэтому запускать его нужно из окружения API.

Запуск (из корня проекта):
    /Users/excummicado69/Desktop/gitv/api/venv/bin/python -I tools/bundle-stats/elo_export.py \
        <копия_базы.db> tools/bundle-stats/data/elo_before.csv
Скрипт сам не запускался при подготовке отчёта.
"""

import csv
import os
import sys

DB_COPY = os.path.abspath(sys.argv[1])
OUT_CSV = sys.argv[2]
# Настройка database_url читается при импорте приложения, поэтому задаём её до импорта.
os.environ["DATABASE_URL"] = f"sqlite:///{DB_COPY}"

sys.path.insert(0, "/Users/excummicado69/Desktop/gitv/api")
from sqlmodel import Session
from app.database import engine
import app.services.stats.snapshot as _x
S = sys.modules['app.services.stats.snapshot']
from app.services.stats.elo import elo_ratings
with Session(engine) as s:
    snap = S.build(s, S.current_key(s))
    r = elo_ratings(s, snap)
    rows = {}
    for uid, rt in r.items():
        for st in rt.history:
            rows[(st.match_id, uid)] = st.before
out = OUT_CSV
with open(out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["match_id","user_id","elo_before"])
    for (m,u),b in sorted(rows.items()): w.writerow([m,u,round(b,3)])
print(len(rows), len(r))
