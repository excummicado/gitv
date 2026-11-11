#!/usr/bin/env python3
"""Оценка ускорения прохождения Бездны парами персонажей («связками») по уровням созвездий и пересчёт в цену в очках.

Запуск (один запуск воспроизводит всё, seed фиксирован):
    tools/bundle-stats/.venv/bin/python tools/bundle-stats/model.py
Читает только CSV из data/ (их делают export.py и elo_before.csv), пишет data/results/*.csv.

Версия 3: вес игрока ограничен (K = 40 игр), «игрок x персонаж», уровни созвездий C0..C6 с накопительным («склеивающим»)
штрафом, сетка эффекта пары по уровням обоих персонажей. Ниже описание базовой модели.

Модель: наблюдение = (игрок в игре, комната r), y = время комнаты в секундах, сверху обрезано на 300 (300 - отметка
«комната не пройдена»). Гребневая регрессия с фиксированными эффектами «фаза Бездны x комната», индикаторами
игрока, персонажей (+ созвездия C>=2 и C6), оружием (cost_engines), парами в одной половине восьмёрки и
связками из трёх и более персонажей (и условными связками) актуальной системы. Эффект на игру = коэффициент x 3.
"""

import csv
import itertools
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import scipy.linalg as sla
import scipy.sparse as sp
from scipy import optimize, stats

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RES = DATA / "results"

SEED = 20261111
SINCE = "2025-11-11"
HOLDOUT = "2026-08-11"
CENSOR = 300.0
MAX_CLEAR = 900
MIN_GAMES, MIN_PLAYERS, MIN_COND_GAMES = 30, 8, 30
MIN_AGENT_GAMES = 10  # персонаж с меньшим числом игр не получает своей колонки (в спецификации порога нет)
WEIGHT_CAP = 40  # K: суммарный вес игрока не больше K игр
PA_MIN_GAMES = 5  # «игрок x персонаж»: от скольких игр у игрока на персонаже
MIN_SUP = 3  # колонка сетки пары нужна, если активна хотя бы в стольких играх
CELL_MEASURED_GAMES, CELL_MEASURED_PLAYERS = 20, 5
ROBUST_MIN_PLAYERS = 15
N_BOOT = 500
N_SPLITS = 6
N_FOLDS = 5
BH_Q = 0.1
ROOMS_PER_GAME = 3

# Штрафы - в единицах суммы квадратов остатков (y в секундах на комнату); сетки - GRIDS ниже
MIN_INSEP_GAMES, INSEP_SHARE = 30, 0.8
MIN_TEAM_GAMES, MIN_TEAM_PLAYERS = 20, 6
FE_PEN, NUM_PEN = 1e-3, 1e-3

# Аккаунт smert (HotH: Abyss Weekend 6, Smertik) одалживали другим: в этих турнирах составы игроков - его.
# Эти (игрок, турнир) выделены в отдельных «игроков» (по memory: shared-game-accounts).
SHARED_ACCOUNT_USES = {
    ("68b3ae294445d6dd2d53f1c7", "68fa917ce9a4076fe82c6bc1"): "raiymbekzmt, Abyss Fast Soup 5",
    ("689224c298475bdb81347f4d", "691454b763ba1aa89cceb645"): "oujikun, Abyss Fast Soup 7",
    ("68a33bffa170389d55235b85", "693ac056b79407da85cd9da2"): "Palm, Abyss Fast Soup 9",
}


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- загрузка и фильтры

def read_csv(name):
    with (DATA / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(s, default=None):
    if s is None or s == "":
        return default
    return float(s)


def adjusted_time(clear_time, restarts, free, paid):
    """Перенесено из api/app/services/match_checks.py: clear_time плюс paid[k] секунд за k-й рестарт сверх бесплатных
    (последнее значение повторяется)."""
    extra = max(0, restarts - (free or 0))
    return clear_time + sum(paid[min(k, len(paid) - 1)] for k in range(extra)) if paid else clear_time


def load_games():
    merges = {r["user_id"]: r["into_id"] for r in read_csv("playermerge.csv")}

    def merged(u):
        seen = set()
        while u in merges and u not in seen:
            seen.add(u)
            u = merges[u]
        return u

    picks = defaultdict(list)
    names = {}
    for r in read_csv("picks.csv"):
        if r["agent_id"]:
            picks[r["matchplayer_id"]].append((int(r["position"]), r["agent_id"], int(r["mindscape"])))
            names[r["agent_id"]] = (r["agent_name_en"], r["agent_name_ru"])
    elo = {(r["match_id"], r["user_id"]): float(r["elo_before"]) for r in read_csv("elo_before.csv")}

    reasons = Counter()
    room_reasons = Counter()
    games = []
    n_raw = 0
    for r in read_csv("player_games.csv"):
        n_raw += 1
        if r["created_at"] < SINCE:
            reasons["created_at < " + SINCE] += 1
            continue
        pk = sorted(picks.get(r["matchplayer_id"], []))
        if int(r["n_picks"]) != 8 or len(pk) != 8:
            reasons["n_picks != 8"] += 1
            continue
        if len({a for _, a, _ in pk}) != 8:
            reasons["повтор персонажа у игрока"] += 1
            continue
        ct = num(r["clear_time"])
        if ct is None or not ct <= MAX_CLEAR:
            reasons[f"clear_time > {MAX_CLEAR}"] += 1
            continue
        if not r["abyss_phase"]:
            reasons["нет фазы Бездны"] += 1
            continue
        rc = int(num(r["room_count"], 3))
        rooms = []
        for i in (1, 2, 3):
            v = num(r[f"room{i}"])
            if i > rc:
                if v is not None and v > 0:
                    room_reasons["комната 3 при room_count = 2 (строк)"] += 1
                continue
            if v is None or v <= 0:
                room_reasons["комната пуста или <= 0 (строк)"] += 1
                continue
            rooms.append((i - 1, v))
        if not rooms:
            reasons["нет ни одной годной комнаты"] += 1
            continue
        raw_uid = r["user_id"] or ("name:" + r["full_name"])
        uid = merged(raw_uid)
        if (uid, r["tournament_id"]) in SHARED_ACCOUNT_USES:
            uid = f"{uid}@{r['tournament_id']}"
        paid = json.loads(r["paid_restarts"]) if r["paid_restarts"] else []
        e = elo.get((r["match_id"], raw_uid))
        if e is None:
            e = elo.get((r["match_id"], uid.split("@")[0]))
        games.append({
            "mpid": r["matchplayer_id"], "uid": uid, "tid": r["tournament_id"], "match": r["match_id"],
            "created": r["created_at"], "phase": r["abyss_phase"], "rooms": rooms, "n_rooms": rc,
            "full": len(rooms) == rc,
            "agents": [a for _, a, _ in pk], "mind": {a: m for _, a, m in pk},
            "half": [frozenset(a for _, a, _ in pk[:4]), frozenset(a for _, a, _ in pk[4:])],
            "cost_engines": num(r["cost_engines"]), "elo": e,
            "adj": adjusted_time(ct, int(num(r["restarts"], 0)), int(num(r["free_restarts"], 0)), paid),
            "raw_uid": raw_uid, "clear": ct,
            "lv": {a: clamp_level(m) for _, a, m in pk},
        })
    return games, names, reasons, room_reasons, n_raw


# ---------------------------------------------------------------- план признаков

GROUPS_P = ("fe", "player", "num", "agent", "lvl", "pa", "pair0", "pairm", "pairc", "extra")
GI = {g: i for i, g in enumerate(GROUPS_P)}
BIG = 1e12


def clamp_level(m):
    return int(min(max(m, 0), 6))


def player_weights(games):
    """w = min(1, K / число игр игрока): суммарный вес игрока не больше K игр (игроки как в модели, после слияний)."""
    n = Counter(g["uid"] for g in games)
    return {u: min(1.0, WEIGHT_CAP / c) for u, c in n.items()}


class Spec:
    """Список колонок модели; пороги считаются по тем играм, на которых его строят.

    Колонки: фаза x комната, игрок, elo/оружие, персонаж (уровень C0), уровни созвездий персонажа C1..C6
    (накопительные индикаторы C>=k со штрафом на разности соседних уровней), «игрок x персонаж» (>= 5 игр),
    пары (накопительная сетка по уровням обоих: индикаторы CA>=i и CB>=j, i,j = 0..6; (0,0) - база пары,
    (i,0), (0,j) - аддитивные поправки по уровню, (i,j>=1) - поправки ячейки), связки из трёх и более.
    Колонки с одинаковым набором игр склеены в одну (штраф - параллельное соединение штрафов членов)."""

    def __init__(self, games, bundles):
        self.fe = sorted({(g["phase"], r) for g in games for r, _ in g["rooms"]})
        self.fe_idx = {k: i for i, k in enumerate(self.fe)}
        self.players = sorted({g["uid"] for g in games})
        el = np.array([g["elo"] for g in games if g["elo"] is not None])
        co = np.array([g["cost_engines"] for g in games if g["cost_engines"] is not None])
        self.elo_mu, self.elo_sd = el.mean(), el.std()
        self.co_mu, self.co_sd = co.mean(), co.std()
        agent_games = Counter(a for g in games for a in g["agents"])
        self.agents = sorted(a for a, n in agent_games.items() if n >= MIN_AGENT_GAMES)
        agent_set = set(self.agents)
        # пары: >= 30 игр и >= 8 разных игроков
        cnt, who = Counter(), defaultdict(set)
        for g in games:
            for h in g["half"]:
                for p in itertools.combinations(sorted(h), 2):
                    cnt[p] += 1
                    who[p].add(g["uid"])
        self.pairs = sorted(p for p, n in cnt.items() if n >= MIN_GAMES and len(who[p]) >= MIN_PLAYERS)
        self.pair_count = {p: (cnt[p], len(who[p])) for p in cnt}
        self.insep = inseparable_pairs(games)
        pair_set = set(self.pairs)
        # уровни созвездий: игры, где C>=k
        lv_games = defaultdict(list)
        for gi, g in enumerate(games):
            for a in g["agents"]:
                if a in agent_set:
                    for k in range(1, g["lv"][a] + 1):
                        lv_games[(a, k)].append(gi)
        # сетка пар: игры, где в одной половине пара и (CA >= i, CB >= j)
        pf_games = defaultdict(list)
        for gi, g in enumerate(games):
            for h in g["half"]:
                for p in itertools.combinations(sorted(h), 2):
                    if p in pair_set:
                        ca, cb = g["lv"][p[0]], g["lv"][p[1]]
                        for i in range(ca + 1):
                            for j in range(cb + 1):
                                pf_games[(p, i, j)].append(gi)
        # игрок x персонаж
        pa_n = Counter((g["uid"], a) for g in games for a in g["agents"] if a in agent_set)
        self.pa = sorted(k for k, n in pa_n.items() if n >= PA_MIN_GAMES)
        # связки из трёх и более (двухперсонажные, в том числе условные, читаются из сетки пар)
        self.extra = []
        seen = set()
        for b in bundles:
            key = (b["agents"], b["conds"])
            if key in seen or len(b["agents"]) == 2:
                continue
            seen.add(key)
            n = sum(1 for g in games if bundle_hit(g, b["agents"], b["conds"]))
            if b["conds"] is not None:
                ok = n >= MIN_COND_GAMES
            else:
                ng = {g["uid"] for g in games if bundle_hit(g, b["agents"], None)}
                ok = n >= MIN_GAMES and len(ng) >= MIN_PLAYERS
            if ok:
                self.extra.append(key)

        # ---- раскладка колонок
        cols = []  # (family, key, {group: count})
        for k in self.fe:
            cols.append(("fe", k, {"fe": 1}))
        for u in self.players:
            cols.append(("player", u, {"player": 1}))
        for k in range(2):
            cols.append(("num", k, {"num": 1}))
        for a in self.agents:
            cols.append(("agent", a, {"agent": 1}))
        merged = {}
        self.lvl_members, self.pair_members = {}, {}
        for (a, k), gis in sorted(lv_games.items()):
            key = (a, tuple(gis))
            if key not in merged:
                merged[key] = len(cols)
                cols.append(("lvl", (a, k), {}))
                self.lvl_members[len(cols) - 1] = []
            j = merged[key]
            cols[j][2]["lvl"] = cols[j][2].get("lvl", 0) + 1
            self.lvl_members[j].append((a, k))
        for u, a in self.pa:
            cols.append(("pa", (u, a), {"pa": 1}))
        merged = {}
        for (p, i, j_), gis in sorted(pf_games.items()):
            if (i, j_) != (0, 0) and len(gis) < MIN_SUP:
                continue
            key = (p, tuple(gis))
            if key not in merged:
                merged[key] = len(cols)
                cols.append(("pair", (p, i, j_), {}))
                self.pair_members[len(cols) - 1] = []
            j = merged[key]
            grp = "pair0" if (i, j_) == (0, 0) else ("pairm" if i == 0 or j_ == 0 else "pairc")
            cols[j][2][grp] = cols[j][2].get(grp, 0) + 1
            self.pair_members[j].append((p, i, j_))
        for k in self.extra:
            cols.append(("extra", k, {"extra": 1}))
        self.cols = cols
        self.p = len(cols)
        self.cnt = np.zeros((self.p, len(GROUPS_P)))
        for j, (_, _, gc) in enumerate(cols):
            for g_, c_ in gc.items():
                self.cnt[j, GI[g_]] = c_
        self.slices = {}
        fam = [c[0] for c in cols]
        for name in ("fe", "player", "num", "agent", "lvl", "pa", "pair", "extra"):
            idx = [j for j, f in enumerate(fam) if f == name]
            self.slices[name] = (idx[0], idx[-1] + 1) if idx else (0, 0)
        self.fam = np.array(fam)
        self.player_col = {c[1]: j for j, c in enumerate(cols) if c[0] == "player"}
        self.agent_col = {c[1]: j for j, c in enumerate(cols) if c[0] == "agent"}
        self.pa_col = {c[1]: j for j, c in enumerate(cols) if c[0] == "pa"}
        self.extra_col = {c[1]: j for j, c in enumerate(cols) if c[0] == "extra"}
        self.lvl_col = {m: j for j, ms in self.lvl_members.items() for m in ms}
        self.pair_feat_col = {m: j for j, ms in self.pair_members.items() for m in ms}
        # колонки каждой из 49 ячеек пары (множество склеенных колонок)
        self.cell_cols = {}
        for p in self.pairs:
            for ca in range(7):
                for cb in range(7):
                    self.cell_cols[(p, ca, cb)] = np.array(sorted({
                        self.pair_feat_col[(p, i, j_)] for i in range(ca + 1) for j_ in range(cb + 1)
                        if (p, i, j_) in self.pair_feat_col}), int)

    def lam_vec(self, lam):
        v = np.empty(len(GROUPS_P))
        for name, val in (("fe", FE_PEN), ("player", lam["lp"]), ("num", NUM_PEN), ("agent", lam["la"]),
                          ("lvl", lam["ll"]), ("pa", lam["lpa"]), ("pair0", lam["lq"]), ("pairm", lam["lm"]),
                          ("pairc", lam["lc"]), ("extra", lam["lq"])):
            v[GI[name]] = val
        return v

    def pen(self, lam):
        """Штраф на колонку: параллельное соединение штрафов склеенных членов."""
        inv = 1.0 / self.lam_vec(lam)
        s = self.cnt @ inv
        return 1.0 / np.maximum(s, 1e-30)

    def shares(self, lam):
        """Доли члена склеенной колонки: пропорционально 1 / штраф группы (для разворота в уровни и ячейки)."""
        inv = 1.0 / self.lam_vec(lam)
        tot = self.cnt @ inv
        out = {}
        for j, ms in self.pair_members.items():
            for m in ms:
                (i, j_) = m[1], m[2]
                grp = "pair0" if (i, j_) == (0, 0) else ("pairm" if i == 0 or j_ == 0 else "pairc")
                out[m] = inv[GI[grp]] / tot[j]
        for j, ms in self.lvl_members.items():
            for m in ms:
                out[m] = inv[GI["lvl"]] / tot[j]
        return out


def cbin(m):
    return "high" if m >= 6 else ("mid" if m >= 2 else "low")


def inseparable_pairs(games):
    """{(a, b): статистика} для упорядоченных пар с n_a >= 30 и p_same_half >= 0.8 («в одной половине») или
    p_same_draft >= 0.8 при p_same_half < 0.8 (в одном драфте)."""
    out = {}
    for (a, b), st in pair_stats(games).items():
        if st["n_a"] >= MIN_INSEP_GAMES and (st["p_half"] >= INSEP_SHARE or st["p_draft"] >= INSEP_SHARE):
            out[(a, b)] = st
    return out


def pair_stats(games):
    n_a, pl_a = Counter(), defaultdict(set)
    same, samed = Counter(), Counter()
    for g in games:
        for a in g["agents"]:
            n_a[a] += 1
            pl_a[a].add(g["uid"])
        for h in g["half"]:
            for a, b in itertools.permutations(h, 2):
                same[(a, b)] += 1
        for a, b in itertools.permutations(g["agents"], 2):
            samed[(a, b)] += 1
    return {(a, b): {"n_a": n_a[a], "players_a": len(pl_a[a]), "p_half": same[(a, b)] / n_a[a],
                     "p_draft": c / n_a[a], "n_half": same[(a, b)]}
            for (a, b), c in samed.items()}


def bundle_hit(g, agents, conds):
    for h in g["half"]:
        if set(agents) <= h:
            if conds is None:
                return True
            return all(lo <= g["mind"][a] <= hi for a, (lo, hi) in zip(agents, conds))
    return False


def game_matrix(spec, games, wg):
    """Матрица G x p без фиксированных эффектов: признаки игр."""
    rows, cols, vals = [], [], []

    def add(i, j, v=1.0):
        rows.append(i)
        cols.append(j)
        vals.append(v)

    for i, g in enumerate(games):
        j = spec.player_col.get(g["uid"])
        if j is not None:
            add(i, j)
        add(i, spec.slices["num"][0], 0.0 if g["elo"] is None else (g["elo"] - spec.elo_mu) / spec.elo_sd)
        add(i, spec.slices["num"][0] + 1,
            0.0 if g["cost_engines"] is None else (g["cost_engines"] - spec.co_mu) / spec.co_sd)
        for a in g["agents"]:
            j = spec.agent_col.get(a)
            if j is not None:
                add(i, j)
                for c in {spec.lvl_col[(a, k)] for k in range(1, g["lv"][a] + 1) if (a, k) in spec.lvl_col}:
                    add(i, c)
            j = spec.pa_col.get((g["uid"], a))
            if j is not None:
                add(i, j)
        for h in g["half"]:
            for p in itertools.combinations(sorted(h), 2):
                cc = spec.cell_cols.get((p, g["lv"][p[0]], g["lv"][p[1]]))
                if cc is not None:
                    for c in cc:
                        add(i, c)
        for key, j in spec.extra_col.items():
            if bundle_hit(g, *key):
                add(i, j)
    return sp.csr_matrix((vals, (rows, cols)), shape=(len(games), spec.p))


class Obs:
    """Строки (игра, комната) с признаками и весами игроков."""

    def __init__(self, spec, games, wg):
        Xg = game_matrix(spec, games, wg)
        gi, room, y = [], [], []
        for i, g in enumerate(games):
            for r, v in g["rooms"]:
                gi.append(i)
                room.append(r)
                y.append(v)
        self.gi = np.array(gi)
        self.y_raw = np.array(y)
        self.y = np.minimum(self.y_raw, CENSOR)
        self.cens = self.y_raw >= CENSOR
        fe = np.array([spec.fe_idx.get((games[i]["phase"], r), -1) for i, r in zip(gi, room)])
        ok = fe >= 0
        fr, fc, fv = list(np.nonzero(ok)[0]), list(fe[ok]), [1.0] * int(ok.sum())
        by_room = defaultdict(list)
        for (ph, r), j in spec.fe_idx.items():
            by_room[r].append(j)
        for i in np.nonzero(~ok)[0]:
            cols_ = by_room[room[i]]
            fr += [i] * len(cols_)
            fc += cols_
            fv += [1.0 / len(cols_)] * len(cols_)
        FE = sp.csr_matrix((fv, (fr, fc)), shape=(len(gi), spec.p))
        self.X = (Xg[self.gi] + FE).tocsr()
        self.uid = np.array([games[i]["uid"] for i in gi])
        self.tid = np.array([games[i]["tid"] for i in gi])
        self.created = np.array([games[i]["created"] for i in gi])
        self.w = np.array([wg[games[i]["uid"]] for i in gi])


# ---------------------------------------------------------------- решатель (разложение Холецкого + PCG)

def gram_dense(X, w):
    Xw = sp.diags(w) @ X
    return (X.T @ Xw).toarray()


class Solver:
    """Обобщённый гребень min sum w (y - Xb)^2 + sum pen_j b_j^2. Разложение Холецкого строится по весам w0;
    решения для других весов (повторы бутстрэпа, фолды, исключённые игроки) - PCG с этим разложением как
    предобуславливателем, сразу для многих столбцов весов."""

    def __init__(self, X, y, w0, pen, G=None, keep=None):
        self.keep = np.ones(X.shape[1], bool) if keep is None else keep
        self.p_full = X.shape[1]
        Xk = X if keep is None else X[:, np.nonzero(keep)[0]]
        self.X = Xk.tocsr()
        self.Xt = Xk.T.tocsr()
        self.y, self.w0 = y, w0
        pen_k = pen[self.keep]
        if G is None:
            A = gram_dense(self.X, w0)
        elif keep is None:
            A = G.copy()
        else:
            ix = np.nonzero(keep)[0]
            A = G[np.ix_(ix, ix)]
        A[np.diag_indices_from(A)] += pen_k
        self.pen = pen_k
        self.cho = sla.cho_factor(A, overwrite_a=True, check_finite=False)
        self.b0 = self.Xt @ (w0 * y)

    def _M(self, R):
        return sla.cho_solve(self.cho, R, check_finite=False)

    def solve(self, W=None, tol=1e-5, maxit=60, y=None):
        """W: n x m веса (None - w0). Возвращает p_full x m коэффициентов."""
        yv = self.y if y is None else y
        if W is None:
            b = (self.Xt @ (self.w0 * yv))[:, None]
            Wm = self.w0[:, None]
        else:
            Wm = W
            b = self.Xt @ (Wm * yv[:, None])
        x = self._M(b)

        def Aw(v):
            return self.Xt @ (Wm * (self.X @ v)) + self.pen[:, None] * v

        r = b - Aw(x)
        bn = np.linalg.norm(b, axis=0) + 1e-30
        z = self._M(r)
        d = z.copy()
        rz = np.sum(r * z, axis=0)
        self.iters = 0
        for it in range(maxit):
            if np.all(np.linalg.norm(r, axis=0) / bn < tol):
                break
            Ad = Aw(d)
            den = np.sum(d * Ad, axis=0)
            alpha = np.where(den > 0, rz / np.where(den > 0, den, 1), 0.0)
            x += alpha * d
            r -= alpha * Ad
            z = self._M(r)
            rz_new = np.sum(r * z, axis=0)
            d = z + (rz_new / np.where(rz > 0, rz, 1)) * d
            rz = rz_new
            self.iters = it + 1
        out = np.zeros((self.p_full, x.shape[1]))
        out[self.keep] = x
        self.rel_res = float((np.linalg.norm(r, axis=0) / bn).max())
        return out


def wrmse(y, pred, w):
    return float(np.sqrt(np.sum(w * (y - pred) ** 2) / np.sum(w)))


def urmse(y, pred):
    return float(np.sqrt(np.mean((y - pred) ** 2)))


# ---------------------------------------------------------------- подбор штрафов

LAM0 = {"lp": 3.0, "la": 30.0, "ll": 30.0, "lpa": 30.0, "lq": 100.0, "lm": 300.0, "lc": 3000.0}
GRIDS = {"lp": (1.0, 3.0, 10.0, 30.0), "la": (3.0, 10.0, 30.0, 100.0, 300.0),
         "ll": (3.0, 10.0, 30.0, 100.0, 300.0, 1000.0), "lpa": (3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0),
         "lq": (30.0, 100.0, 300.0, 1000.0, 3000.0), "lm": (100.0, 300.0, 1000.0, 3000.0, 10000.0, 30000.0),
         "lc": (300.0, 1000.0, 3000.0, 10000.0, 30000.0, 100000.0)}
FREE = {"full": ("lp", "la", "ll", "lpa", "lq", "lm", "lc"), "nogrid": ("lp", "la", "ll", "lpa", "lq"),
        "nopairs": ("lp", "la", "ll", "lpa")}


def variant_lam(variant, lam):
    lam = dict(lam)
    if variant in ("nogrid", "nopairs"):
        lam["lm"] = lam["lc"] = BIG
    if variant == "nopairs":
        lam["lq"] = BIG
    return lam


def keep_for(spec, lam):
    return spec.pen(lam) < 1e9


def fold_assign(obs, seed):
    tids = sorted(set(obs.tid))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(tids))
    fold_of = {tids[i]: k % N_FOLDS for k, i in enumerate(perm)}
    return np.array([fold_of[t] for t in obs.tid])


def cv_eval(spec, obs, G, fold, lam, variant):
    lam_v = variant_lam(variant, lam)
    pen = spec.pen(lam_v)
    keep = pen < 1e9
    sv = Solver(obs.X, obs.y, obs.w, pen, G=G, keep=keep)
    W = obs.w[:, None] * (fold[:, None] != np.arange(N_FOLDS)[None, :])
    B = sv.solve(W, tol=2e-3, maxit=20)
    pred = np.asarray(obs.X @ B)[np.arange(len(obs.y)), fold]
    del sv
    return wrmse(obs.y, pred, obs.w), urmse(obs.y, pred)


def cv_search(spec, obs, G, variant, start, rounds=2, tag=""):
    """Покоординатный подбор штрафов по взвешенной CV (фолды - турниры); возвращает (лучшие lam, метрики, журнал)."""
    fold = fold_assign(obs, SEED)
    cache = {}

    def ev(lam):
        k = tuple(lam[n] for n in FREE[variant])
        if k not in cache:
            cache[k] = cv_eval(spec, obs, G, fold, lam, variant)
        return cache[k][0]

    best, best_s = dict(start), ev(start)
    log(f"  [{tag}{variant}] старт {best_s:.3f}")
    for r in range(rounds):
        improved = False
        for name in FREE[variant]:
            for v in GRIDS[name]:
                if v == best[name]:
                    continue
                cand = {**best, name: v}
                s = ev(cand)
                if s < best_s - 1e-6:
                    best, best_s, improved = cand, s, True
            log(f"  [{tag}{variant}] круг {r + 1}, {name}={best[name]}: {best_s:.3f}")
        if not improved:
            break
    k = tuple(best[n] for n in FREE[variant])
    return best, cache[k], cache
# ---------------------------------------------------------------- Tobit

def tobit_fit(X, y, cens, pen, beta0, w):
    """Штрафованный Tobit (правая цензура на CENSOR). Штраф pen_j * b_j^2 / (2 sigma^2) - тот же гауссов априор,
    что и в гребне."""
    n, p = X.shape
    unc = ~cens
    Xt = X.T.tocsr()

    def f(theta):
        b, ls = theta[:p], theta[p]
        s = np.exp(ls)
        mu = X @ b
        r = (y - mu) / s
        z = (mu - CENSOR) / s
        lc = stats.norm.logcdf(z)
        haz = np.exp(stats.norm.logpdf(z) - lc)
        nll = np.sum(w[unc] * (ls + 0.5 * r[unc] ** 2)) - np.sum((w * lc)[cens]) + 0.5 * np.sum(pen * b * b) / s**2
        gmu = w * np.where(unc, -r / s, -haz / s)
        gb = Xt @ gmu + pen * b / s**2
        gls = np.sum(w[unc] * (1 - r[unc] ** 2)) + np.sum((w * z * haz)[cens]) - np.sum(pen * b * b) / s**2
        return nll, np.append(gb, gls)

    s0 = np.std(y - X @ beta0)  # старт; веса учтены в целевой функции
    out = optimize.minimize(f, np.append(beta0, np.log(s0)), jac=True, method="L-BFGS-B",
                            options={"maxiter": 3000, "maxfun": 5000, "ftol": 1e-12, "gtol": 1e-6})
    return out.x[:p], float(np.exp(out.x[p])), out


# ---------------------------------------------------------------- вспомогательное

def bh(p):
    p = np.asarray(p)
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    run = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        run = min(run, p[i] * n / rank)
        adj[i] = run
    return adj


def corr(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan"), float("nan")
    return float(np.corrcoef(a, b)[0, 1]), float(stats.spearmanr(a, b)[0])


def load_bundles(system_id):
    ru_names = {r["agent_id"]: r["name_ru"] for r in read_csv("agents_meta.csv")} \
        if (DATA / "agents_meta.csv").exists() else {}
    by = defaultdict(list)
    for r in read_csv("bundles.csv"):
        if r["system_id"] == system_id:
            by[r["bundle_id"]].append(r)
    out = []
    for bid, rows in by.items():
        rows = sorted(rows, key=lambda r: r["agent_id"])
        conds = tuple((int(num(r["mindscape_min"], 0)), int(num(r["mindscape_max"], 6))) for r in rows)
        trivial = all(r["mindscape_min"] in ("", "0") and r["mindscape_max"] == "" for r in rows)
        out.append({
            "id": bid, "cost": float(rows[0]["cost"]), "tier": rows[0]["required_tier"],
            "agents": tuple(r["agent_id"] for r in rows), "names": [r["agent_name_en"] for r in rows],
            "names_ru": [ru_names.get(r["agent_id"]) or r["agent_name_en"] for r in rows],
            "conds": None if trivial else conds,
        })
    return out


def read_csv_path(path):
    with Path(path).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def top3_share(counter, n):
    return sum(c for _, c in counter.most_common(3)) / n


def fmt(x, nd=1):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


# ---------------------------------------------------------------- сохранённая модель и оценка команд

COEFS_JSON = RES / "coefs.json"
COEFS_BOOT = RES / "coefs_boot.npz"
GROUPS = ("agent", "pair", "const", "extra")  # группы слагаемых в разложении оценки команды


class Coefs:
    """Коэффициенты модели в терминах «членов» (без игроков, фазы, числовых признаков и «игрок x персонаж»).
    keys[i] - один из: ("agent", a) - эффект персонажа на C0; ("lvl", a, k) - прибавка уровня C>=k (накопительно);
    ("pair", a, b, i, j) - член сетки пары (CA>=i и CB>=j; (0,0) - база пары); ("extra", agents, conds).
    vec[i] - коэффициент на комнату; эффект на игру = коэффициент x 3."""

    def __init__(self, keys, vec, names, typical, boots=None):
        self.keys = [tuple(k) for k in keys]
        self.vec = np.asarray(vec, float)
        self.names = names  # id -> (en, ru)
        self.typical = typical  # id -> типичное созвездие
        self.boots = boots  # N x k или None
        self.index = {k: i for i, k in enumerate(self.keys)}
        self.agents = {k[1] for k in self.keys if k[0] == "agent"}
        self.extras = [k for k in self.keys if k[0] == "extra"]
        self.by_en = {v[0].lower(): a for a, v in names.items()}
        self.group = np.array([("agent" if k[0] in ("agent", "lvl") else
                                ("extra" if k[0] == "extra" else ("pair" if k[3] == 0 and k[4] == 0 else "const")))
                               for k in self.keys])
        self.baseline = None  # среднее число вхождений каждого члена на половину (взвешенное)

    def half_terms(self, half, mind):
        """Индексы членов, «включённых» у четвёрки (множество id) при созвездиях mind {id: C}."""
        half = set(half)
        lv = {a: clamp_level(mind.get(a, self.typical.get(a, 0))) for a in half}
        idx, missing = [], []
        for a in half:
            i = self.index.get(("agent", a))
            if i is not None:
                idx.append(i)
            for k in range(1, lv[a] + 1):
                i = self.index.get(("lvl", a, k))
                if i is not None:
                    idx.append(i)
        for p in itertools.combinations(sorted(half), 2):
            if ("pair", p[0], p[1], 0, 0) not in self.index:
                missing.append(p)
                continue
            for i in range(lv[p[0]] + 1):
                for j in range(lv[p[1]] + 1):
                    ix = self.index.get(("pair", p[0], p[1], i, j))
                    if ix is not None:
                        idx.append(ix)
        fake = {"half": [half], "mind": lv}
        for k in self.extras:
            if bundle_hit(fake, k[1], k[2]):
                idx.append(self.index[k])
        return idx, missing

    def vector(self, half, mind):
        v = np.zeros(len(self.keys))
        idx, missing = self.half_terms(half, mind)
        np.add.at(v, idx, 1.0)
        return v, missing

    def set_baseline(self, games, wg):
        m = np.zeros(len(self.keys))
        tot = 0.0
        for g in games:
            w = wg[g["uid"]]
            for h in g["half"]:
                v, _ = self.vector(h, g["lv"])
                m += w * v
                tot += w
        self.baseline = m / tot

    def save(self):
        doc = {"rooms_per_game": ROOMS_PER_GAME, "keys": [list(k) for k in self.keys],
               "coef": self.vec.tolist(), "baseline": self.baseline.tolist(),
               "names": {a: list(v) for a, v in self.names.items()}, "typical": self.typical}
        COEFS_JSON.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        if self.boots is not None:
            np.savez_compressed(COEFS_BOOT, boots=self.boots.astype(np.float32))

    @classmethod
    def load(cls):
        doc = json.loads(COEFS_JSON.read_text(encoding="utf-8"))
        keys = []
        for k in doc["keys"]:
            if k[0] == "extra":
                keys.append(("extra", tuple(k[1]), None if k[2] is None else tuple(tuple(c) for c in k[2])))
            else:
                keys.append(tuple(k))
        boots = np.load(COEFS_BOOT)["boots"].astype(float) if COEFS_BOOT.exists() else None
        c = cls(keys, doc["coef"], {a: tuple(v) for a, v in doc["names"].items()}, doc["typical"], boots)
        c.baseline = np.array(doc["baseline"])
        return c

    def resolve(self, name):
        if name in self.names:
            return name
        a = self.by_en.get(name.strip().lower())
        if a is None:
            raise KeyError(f"неизвестный персонаж: {name}")
        return a


def team_breakdown(coefs, half, mind=None, interval=True):
    """Разложение эффекта четвёрки: слагаемые относительно среднего по наблюдавшимся половинам (сек на игру)."""
    v, missing = coefs.vector(half, mind or {})
    d = v - coefs.baseline
    parts = {g: float((d * coefs.vec)[coefs.group == g].sum()) * ROOMS_PER_GAME for g in GROUPS}
    out = {"effect": sum(parts.values()), "parts": parts, "n_pairs_unestimated": len(missing),
           "unestimated_pairs": missing}
    if interval and coefs.boots is not None:
        bt = coefs.boots @ d * ROOMS_PER_GAME
        out["ci"] = (float(np.percentile(bt, 5)), float(np.percentile(bt, 95)))
    return out


def score_team(agents, mindscapes=None, coefs=None):
    """Оценка четвёрки по сохранённым коэффициентам (data/results/coefs.json), без пересчёта модели.

    agents: четыре имени (en) или id. mindscapes: None (типичное созвездие каждого персонажа), словарь
    {имя или id: C} или список из четырёх чисел/None. Возвращает словарь: effect - эффект в секундах на игру
    относительно среднего по наблюдавшимся командам (меньше - быстрее); parts - слагаемые (agent: персонажи
    с их уровнями созвездий, pair: базы пар, const: поправки пар по уровням и ячейкам сетки, extra: тройки
    и условные связки); n_pairs_unestimated и unestimated_pairs - пары без оценки (считаются нулём);
    ci - 90% интервал бутстрэпа суммы (если есть coefs_boot.npz); unknown_agents - персонажи без своей оценки."""
    coefs = coefs or Coefs.load()
    ids = [coefs.resolve(a) for a in agents]
    if len(set(ids)) != 4:
        raise ValueError("нужны ровно четыре разных персонажа")
    mind = {}
    if isinstance(mindscapes, dict):
        for k, m in mindscapes.items():
            mind[coefs.resolve(k)] = clamp_level(int(m))
    elif mindscapes is not None:
        for a, m in zip(ids, mindscapes):
            if m is not None:
                mind[a] = clamp_level(int(m))
    out = team_breakdown(coefs, set(ids), mind)
    out["unknown_agents"] = [coefs.names[a][0] for a in ids if a not in coefs.agents]
    out["unestimated_pairs"] = [(coefs.names[a][0], coefs.names[b][0]) for a, b in out["unestimated_pairs"]]
    out["mindscapes"] = {coefs.names[a][0]: mind.get(a, coefs.typical.get(a, 0)) for a in ids}
    return out


def cli_score(arg, mind_arg):
    coefs = Coefs.load()
    mind = None
    if mind_arg:
        mind = {k.strip(): int(v) for k, v in (kv.split("=") for kv in mind_arg.split(","))}
    r = score_team([x.strip() for x in arg.split(",")], mind, coefs)
    print(f"Команда: {arg}; созвездия: {r['mindscapes']}")
    ci = r.get("ci")
    print(f"Эффект относительно среднего: {r['effect']:.1f} с/игру" +
          (f" [90%: {ci[0]:.1f}; {ci[1]:.1f}]" if ci else "") + "  (меньше нуля - быстрее)")
    for g, label in (("agent", "персонажи (с уровнями созвездий)"), ("pair", "базы пар"),
                     ("const", "поправки пар по уровням и ячейкам сетки"), ("extra", "тройки и условные связки")):
        print(f"  {label}: {r['parts'][g]:.1f}")
    print(f"Пар без оценки: {r['n_pairs_unestimated']}" +
          (": " + ", ".join(f"{a}+{b}" for a, b in r["unestimated_pairs"]) if r["unestimated_pairs"] else ""))
    if r["unknown_agents"]:
        print("Персонажи без своей оценки (эффект 0):", ", ".join(r["unknown_agents"]))


def write_rows(name, cols, rows):
    with (RES / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            out = []
            for c in cols:
                v = r.get(c)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    out.append("")
                elif isinstance(v, (float, np.floating)):
                    out.append(f"{v:.4f}")
                else:
                    out.append(v)
            w.writerow(out)


def pct(M, axis=1):
    return np.percentile(M, 5, axis=axis), np.percentile(M, 95, axis=axis)


REUSE_LAM = "--reuse-lam" in sys.argv


def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    RES.mkdir(parents=True, exist_ok=True)
    T = lambda: f"{time.time() - t0:.0f} с"  # noqa: E731

    # ----- 1. данные
    games, names, reasons, room_reasons, n_raw = load_games()
    wpl = player_weights(games)
    all_rows = read_csv("player_games.csv")
    cur_sys = max((r for r in all_rows if r["system_title"] == "Abyss Cup"), key=lambda r: r["created_at"])["system_id"]
    bundles = load_bundles(cur_sys)
    log("=== 1. Данные и фильтры")
    log(f"игр (matchplayer) в выгрузке: {n_raw}")
    for k, v in reasons.items():
        log(f"  отсеяно игр: {k}: {v}")
    for k, v in room_reasons.items():
        log(f"  отсеяно {k} (строк): {v}")
    spec = Spec(games, bundles)
    obs = Obs(spec, games, wpl)
    n_pl = Counter(g["uid"] for g in games)
    log(f"осталось игр: {len(games)}, наблюдений (комнат): {len(obs.y)}, из них y >= 300: {int(obs.cens.sum())} "
        f"({obs.cens.mean():.1%}); игроков (после слияний и разделения): {len(spec.players)}")
    log(f"веса игроков (K = {WEIGHT_CAP}): игроков с весом < 1: {sum(1 for v in wpl.values() if v < 1)}; сумма весов игр "
        f"{sum(wpl[g['uid']] for g in games):.0f} из {len(games)}; максимум игр у игрока {max(n_pl.values())}")
    log(f"игр без elo_before: {sum(1 for g in games if g['elo'] is None)}; без cost_engines: "
        f"{sum(1 for g in games if g['cost_engines'] is None)} (в обоих случаях подставлено среднее)")
    npair_cols = int(sum(1 for c in spec.cols if c[0] == "pair"))
    log(f"колонок: {spec.p} (фаза x комната {len(spec.fe)}, игроки {len(spec.players)}, персонажи {len(spec.agents)}, "
        f"склеенных уровней созвездий {len(spec.lvl_members)} из {len(spec.lvl_col)}, игрок x персонаж {len(spec.pa)}, "
        f"пар {len(spec.pairs)}, склеенных колонок сетки пар {npair_cols} из {len(spec.pair_feat_col)} членов, "
        f"связки из трёх+ {len(spec.extra)})")
    log(f"текущая система: {cur_sys}, связок {len(bundles)}; неразлучных упорядоченных пар: {len(spec.insep)}")

    # ----- 2. подбор штрафов
    log(f"\n=== 2. Взвешенная кросс-валидация по tournament_id ({T()})")
    G = gram_dense(obs.X, obs.w)
    log(f"gram {G.shape} построен ({T()})")
    cache_f = RES / "lam_cache.json"
    if REUSE_LAM and cache_f.exists():
        c_ = json.loads(cache_f.read_text(encoding="utf-8"))
        best_full, best_ng, best_np = c_["full"], c_["nogrid"], c_["nopairs"]
        m_full, m_ng, m_np = c_["m_full"], c_["m_ng"], c_["m_np"]
        log(f"штрафы и метрики CV взяты из {cache_f.name} (подбор не повторялся): {best_full}; CV full {m_full}, "
            f"nogrid {m_ng}, nopairs {m_np}")
    else:
        best_full, m_full, _ = cv_search(spec, obs, G, "full", LAM0)
        log(f"выбрано (full): {best_full}; взвешенный RMSE {m_full[0]:.3f}, невзвешенный {m_full[1]:.3f} ({T()})")
        best_ng, m_ng, _ = cv_search(spec, obs, G, "nogrid", best_full, tag="")
        log(f"выбрано (только база пар, без сетки): {({k: best_ng[k] for k in FREE['nogrid']})}; взвешенный {m_ng[0]:.3f}, "
            f"невзвешенный {m_ng[1]:.3f} ({T()})")
        best_np, m_np, _ = cv_search(spec, obs, G, "nopairs", best_full, tag="")
        log(f"выбрано (без пар): {({k: best_np[k] for k in FREE['nopairs']})}; взвешенный {m_np[0]:.3f}, "
            f"невзвешенный {m_np[1]:.3f} ({T()})")
        cache_f.write_text(json.dumps({"full": best_full, "nogrid": best_ng, "nopairs": best_np, "m_full": list(m_full),
                                       "m_ng": list(m_ng), "m_np": list(m_np)}), encoding="utf-8")
    LAMF = best_full
    at_edge = {n: LAMF[n] == GRIDS[n][-1] for n in ("lm", "lc")}
    log(f"штрафы поправок сетки упёрлись в верхний край сетки: {at_edge}")
    pen = spec.pen(LAMF)

    # ----- 3. основной расчёт
    log(f"\n=== 3. Основной расчёт ({T()})")
    solver = Solver(obs.X, obs.y, obs.w, pen, G=G)
    beta = solver.solve()[:, 0]
    wr = wrmse(obs.y, obs.X @ beta, obs.w)
    log(f"взвешенный RMSE на обучении {wr:.3f}, невзвешенный {urmse(obs.y, obs.X @ beta):.3f}")

    # ----- 4. отложенная проверка
    log(f"\n=== 4. Отложенная проверка: обучение до {HOLDOUT}, тест позже ({T()})")
    g_tr = [g for g in games if g["created"][:10] < HOLDOUT]
    g_te = [g for g in games if g["created"][:10] >= HOLDOUT]
    w_tr, w_te = player_weights(g_tr), player_weights(g_te)
    sp_tr = Spec(g_tr, bundles)
    o_tr, o_te = Obs(sp_tr, g_tr, w_tr), Obs(sp_tr, g_te, w_te)
    log(f"игр в обучении {len(g_tr)} (строк {len(o_tr.y)}), в тесте {len(g_te)} (строк {len(o_te.y)}); "
        f"пар в обучающем наборе: {len(sp_tr.pairs)}; штрафы взяты из подбора на всех данных (не пересчитывались)")
    G_tr = gram_dense(o_tr.X, o_tr.w)
    preds, res_h = {}, {}
    seen_players = np.isin(o_te.uid, sp_tr.players)
    for variant, lam in (("full", best_full), ("nogrid", best_ng), ("nopairs", best_np)):
        pen_v = sp_tr.pen(variant_lam(variant, lam))
        sv = Solver(o_tr.X, o_tr.y, o_tr.w, pen_v, G=G_tr, keep=pen_v < 1e9)
        bv = sv.solve()[:, 0]
        del sv
        preds[variant] = np.asarray(o_te.X @ bv)
        res_h[variant] = {"w": wrmse(o_te.y, preds[variant], o_te.w), "u": urmse(o_te.y, preds[variant]),
                          "seen_u": urmse(o_te.y[seen_players], preds[variant][seen_players])}
    del G_tr
    fk = np.zeros(sp_tr.p, bool)
    fk[:sp_tr.slices["fe"][1]] = True
    A_fe = gram_dense(o_tr.X[:, np.nonzero(fk)[0]], o_tr.w)
    A_fe[np.diag_indices_from(A_fe)] += 1.0
    b_fe = np.zeros(sp_tr.p)
    b_fe[fk] = sla.solve(A_fe, o_tr.X[:, np.nonzero(fk)[0]].T @ (o_tr.w * o_tr.y), assume_a="pos")
    pred_fe = np.asarray(o_te.X @ b_fe)
    res_h["fe"] = {"w": wrmse(o_te.y, pred_fe, o_te.w), "u": urmse(o_te.y, pred_fe)}
    for k, v in res_h.items():
        log(f"  тест, {k}: взвешенный RMSE {v['w']:.3f}, невзвешенный {v['u']:.3f}" +
            (f", игроки, виденные в обучении ({seen_players.mean():.0%}): {v['seen_u']:.3f}" if "seen_u" in v else ""))
    ucl = sorted(set(o_te.uid))
    idx = {u: np.nonzero(o_te.uid == u)[0] for u in ucl}
    picks_ = [np.concatenate([idx[ucl[i]] for i in rng.choice(len(ucl), len(ucl))]) for _ in range(500)]
    holdout_diff = {}
    for label, a_, b_ in (("полная модель - без пар", "full", "nopairs"), ("база пар (без сетки) - без пар", "nogrid", "nopairs"),
                          ("полная - база пар", "full", "nogrid")):
        d2 = (o_te.y - preds[a_]) ** 2 - (o_te.y - preds[b_]) ** 2
        diffs = [np.mean(d2[sel]) for sel in picks_]
        holdout_diff[label] = (float(d2.mean()), float(np.percentile(diffs, 5)), float(np.percentile(diffs, 95)))
        log(f"  разность MSE ({label}) = {d2.mean():.2f}, 90% интервал бутстрэпа по игрокам "
            f"[{np.percentile(diffs, 5):.2f}; {np.percentile(diffs, 95):.2f}] (меньше нуля - первое лучше)")
    holdout = {k: v for k, v in res_h.items()}
    holdout["n_te"], holdout["n_tr"] = len(g_te), len(g_tr)
    del preds

    # ----- 5. бутстрэп
    log(f"\n=== 5. Кластерный бутстрэп по игрокам, {N_BOOT} повторов, веса игроков те же ({T()})")
    cl_players = spec.players
    cl_idx = {u: i for i, u in enumerate(cl_players)}
    row_cl = np.array([cl_idx[u] for u in obs.uid])
    boots = np.empty((N_BOOT, spec.p))
    chunk = 100
    it_max, rr_max = 0, 0.0
    for s0 in range(0, N_BOOT, chunk):
        m = min(chunk, N_BOOT - s0)
        cnt = np.stack([np.bincount(rng.integers(0, len(cl_players), len(cl_players)), minlength=len(cl_players))
                        for _ in range(m)])
        W = obs.w[:, None] * cnt[:, row_cl].T
        boots[s0:s0 + m] = solver.solve(W).T
        it_max, rr_max = max(it_max, solver.iters), max(rr_max, solver.rel_res)
        log(f"  повторы {s0}-{s0 + m} ({T()}), итераций PCG {solver.iters}, относительная невязка {solver.rel_res:.1e}")

    # ----- 6. объекты модели: члены, уровни, ячейки, итоговые функционалы
    log(f"\n=== 6. Уровни, ячейки сетки и функционалы ({T()})")
    shares = spec.shares(LAMF)
    mem_keys, mem_rows, mem_cols, mem_vals = [], [], [], []

    def add_mem(key, col, share):
        mem_rows.append(len(mem_keys))
        mem_cols.append(col)
        mem_vals.append(share)
        mem_keys.append(key)

    for a in spec.agents:
        add_mem(("agent", a), spec.agent_col[a], 1.0)
    for (a, k), col in sorted(spec.lvl_col.items()):
        add_mem(("lvl", a, k), col, shares[(a, k)])
    for (p, i, j), col in sorted(spec.pair_feat_col.items()):
        add_mem(("pair", p[0], p[1], i, j), col, shares[(p, i, j)])
    for k, col in spec.extra_col.items():
        add_mem(("extra", tuple(k[0]), None if k[1] is None else tuple(map(tuple, k[1]))), col, 1.0)
    Mmat = sp.csr_matrix((mem_vals, (mem_rows, mem_cols)), shape=(len(mem_keys), spec.p))
    mem_idx = {k: i for i, k in enumerate(mem_keys)}
    log(f"членов модели (персонажи, уровни, члены сетки, связки): {len(mem_keys)}")

    def build_levels_cells(Mm):
        r_, c_ = [], []
        for ip, p in enumerate(spec.pairs):
            for ca in range(7):
                for cb in range(7):
                    row = ip * 49 + ca * 7 + cb
                    for i in range(ca + 1):
                        for j in range(cb + 1):
                            ix = mem_idx.get(("pair", p[0], p[1], i, j))
                            if ix is not None:
                                r_.append(row)
                                c_.append(ix)
        Inc = sp.csr_matrix((np.ones(len(r_)), (r_, c_)), shape=(len(spec.pairs) * 49, len(mem_keys)))
        r2, c2 = [], []
        for ia, a in enumerate(spec.agents):
            for c in range(1, 7):
                for k in range(1, c + 1):
                    ix = mem_idx.get(("lvl", a, k))
                    if ix is not None:
                        r2.append(ia * 7 + c)
                        c2.append(ix)
        Inc2 = sp.csr_matrix((np.ones(len(r2)), (r2, c2)), shape=(len(spec.agents) * 7, len(mem_keys)))
        return Inc @ Mm, Inc2 @ Mm

    Lc, La = build_levels_cells(Mmat)  # ячейки (585*49 x p), уровни (117*7 x p): в пространстве склеенных колонок
    pair_idx = {p: i for i, p in enumerate(spec.pairs)}
    agent_idx = {a: i for i, a in enumerate(spec.agents)}
    # статистика ячеек
    pair_games = defaultdict(list)
    cell_n, cell_pl, cell_w = Counter(), defaultdict(set), Counter()
    for gi, g in enumerate(games):
        for h in g["half"]:
            for p in itertools.combinations(sorted(h), 2):
                if p in pair_idx:
                    ca, cb = g["lv"][p[0]], g["lv"][p[1]]
                    pair_games[p].append((gi, ca, cb))
                    cell_n[(p, ca, cb)] += 1
                    cell_pl[(p, ca, cb)].add(g["uid"])
                    cell_w[(p, ca, cb)] += wpl[g["uid"]]

    def pair_functional(p, excl=frozenset()):
        row = np.zeros(spec.p)
        tot = 0.0
        for gi, ca, cb in pair_games[p]:
            u = games[gi]["uid"]
            if u in excl:
                continue
            row[spec.cell_cols[(p, ca, cb)]] += wpl[u]
            tot += wpl[u]
        return row / tot if tot > 0 else None

    Fd = np.array([pair_functional(p) for p in spec.pairs])  # заголовочный эффект пары: средний по её играм (с весами)
    F = sp.csr_matrix(Fd)
    typical = {}
    for a in spec.agents:
        ms = [g["lv"][a] for g in games if a in g["lv"]]
        typical[a] = int(round(float(np.median(ms)))) if ms else 0

    def lvl_row(a, c):
        return La[agent_idx[a] * 7 + c].toarray().ravel() if c > 0 else np.zeros(spec.p)

    def agent_vec(a, c=None):
        v = lvl_row(a, typical[a] if c is None else c)
        v[spec.agent_col[a]] += 1
        return v

    # проверка согласованности Coefs и матрицы признаков
    coefs = Coefs(mem_keys, Mmat @ beta, names, typical, (Mmat @ boots.T).T)
    coefs.set_baseline(games, wpl)
    coefs.save()
    sample = games[:: max(1, len(games) // 400)]
    fam_cols = np.nonzero(np.isin(spec.fam, ("agent", "lvl", "pair", "extra")))[0]
    Xs = game_matrix(spec, sample, wpl)[:, fam_cols].toarray()
    pm = Xs @ beta[fam_cols]
    pc = np.array([sum(float(coefs.vector(h, g["lv"])[0] @ coefs.vec) for h in g["half"]) for g in sample])
    log(f"проверка: вклад персонажей, уровней, пар и связок в модели и в Coefs совпал на {len(sample)} играх: "
        f"{bool(np.allclose(pm, pc, atol=1e-6))} (макс. расхождение {np.abs(pm - pc).max():.2e})")
    assert np.allclose(pm, pc, atol=1e-6)

    # ----- 7. устойчивость
    log(f"\n=== 7. Устойчивость ({T()})")
    cs = []
    for _ in range(N_SPLITS):
        perm = rng.permutation(len(cl_players))
        half = np.zeros(len(cl_players), bool)
        half[perm[: len(perm) // 2]] = True
        W = np.stack([obs.w * h_[row_cl] for h_ in (half, ~half)], axis=1)
        Bh = solver.solve(W)
        est = [F @ Bh[:, k] for k in (0, 1)]
        cs.append(corr(est[0], est[1]))
    cs = np.array(cs)
    stab_corr = float(cs[:, 0].mean())
    log(f"корреляция заголовочных эффектов пар между половинами игроков ({N_SPLITS} разбиений): Пирсон среднее "
        f"{cs[:, 0].mean():.2f} (от {cs[:, 0].min():.2f} до {cs[:, 0].max():.2f}), Спирмен {cs[:, 1].mean():.2f}")

    # ----- 8. Tobit и время со штрафом за рестарты
    log(f"\n=== 8. Tobit и adjusted ({T()})")
    tb, tsig, out = tobit_fit(obs.X, obs.y_raw, obs.cens, pen, beta, obs.w)
    log(f"Tobit сошёлся: {out.success} ({out.nit} итераций), sigma = {tsig:.2f}")
    gm = [g for g in games if g["full"]]
    Xg_ = game_matrix(spec, gm, wpl)
    rows_ = [i for i, g in enumerate(gm) if (g["phase"], 0) in spec.fe_idx]
    FE = sp.csr_matrix((np.ones(len(rows_)), (rows_, [spec.fe_idx[(gm[i]["phase"], 0)] for i in rows_])),
                       shape=(len(gm), spec.p))
    Xa = (Xg_ + FE).tocsr()
    ya = np.array([g["adj"] for g in gm], float)
    wa = np.array([wpl[g["uid"]] for g in gm])
    sv_a = Solver(Xa, ya, wa, pen / ROOMS_PER_GAME)
    beta_adj = sv_a.solve()[:, 0]
    del sv_a
    log(f"игр с полным набором комнат: {len(gm)}, среднее adjusted_time {ya.mean():.1f}")
    c_adj = corr(F @ beta * ROOMS_PER_GAME, F @ beta_adj)
    log(f"корреляция заголовочных эффектов пар (основной x3 и adjusted): Пирсон {c_adj[0]:.3f}, Спирмен {c_adj[1]:.3f}")
    c_tobit = corr(F @ beta, F @ tb)
    log(f"корреляция основного расчёта и Tobit по парам: Пирсон {c_tobit[0]:.3f}, Спирмен {c_tobit[1]:.3f}")

    # ----- 9. эффекты пар (заголовочный = средний по сыгранным ячейкам, с весами игроков)
    pair_eff = F @ beta * ROOMS_PER_GAME
    bt = (F @ boots.T) * ROOMS_PER_GAME
    lo, hi = pct(bt)
    se = bt.std(axis=1, ddof=1)
    z = np.where(se > 0, pair_eff / np.where(se > 0, se, 1), 0.0)
    qval = bh(2 * stats.norm.sf(np.abs(z)))
    reliable = ((lo > 0) | (hi < 0)) & (qval <= BH_Q)
    log(f"\n=== 9. Пары: {len(spec.pairs)}; интервал не включает 0: {int(((lo > 0) | (hi < 0)).sum())}; reliable "
        f"(+ BH q={BH_Q}): {int(reliable.sum())} ({T()})")
    en_ = spec.slices["num"][0]
    log(f"коэффициенты: elo_before (за 1 sd) {beta[en_] * ROOMS_PER_GAME:.1f} сек/игру, cost_engines (за 1 sd) "
        f"{beta[en_ + 1] * ROOMS_PER_GAME:.1f} сек/игру")
    log(f"эффекты пар: среднее {pair_eff.mean():.1f}, медиана {np.median(pair_eff):.1f}, sd {pair_eff.std():.1f}, "
        f"доля < 0: {np.mean(pair_eff < 0):.0%}; средняя ошибка бутстрэпа {se.mean():.1f}")

    # пересчёт без самых частых игроков пары (одного и троих сразу)
    pair_players = defaultdict(Counter)
    for p in spec.pairs:
        for gi, _, _ in pair_games[p]:
            pair_players[p][games[gi]["uid"]] += 1
    solver_cols = []
    for i, p in enumerate(spec.pairs):
        for kk in (1, 3):
            ex = frozenset(u for u, _ in pair_players[p].most_common(kk))
            solver_cols.append((i, kk, ex, pair_functional(p, ex)))
    wo = {}
    for s0 in range(0, len(solver_cols), 100):
        part = solver_cols[s0:s0 + 100]
        W = np.stack([obs.w * ~np.isin(obs.uid, list(ex)) for _, _, ex, _ in part], axis=1)
        B = solver.solve(W)
        for k_, (i, kk, ex, f) in enumerate(part):
            wo[(i, kk)] = float(f @ B[:, k_]) * ROOMS_PER_GAME if f is not None else None
        log(f"  без топ-игроков: {s0 + len(part)} из {len(solver_cols)} ({T()}), итераций {solver.iters}, "
            f"невязка {solver.rel_res:.1e}")
    robust, reason = [], []
    for i, p in enumerate(spec.pairs):
        e, w3 = pair_eff[i], wo[(i, 3)]
        n_pl_ = spec.pair_count[p][1]
        if not reliable[i]:
            why = "не reliable"
        elif w3 is None:
            why = "после удаления трёх игроков не осталось игр"
        elif np.sign(w3) != np.sign(e):
            why = "знак без трёх игроков другой"
        elif abs(w3) < 0.5 * abs(e):
            why = "без трёх игроков эффект меньше половины"
        elif n_pl_ < ROBUST_MIN_PLAYERS:
            why = f"игроков меньше {ROBUST_MIN_PLAYERS}"
        else:
            why = ""
        robust.append(why == "")
        reason.append(why)
    robust = np.array(robust)
    log(f"robust (reliable, знак и >= половины без трёх главных игроков, >= {ROBUST_MIN_PLAYERS} игроков): "
        f"{int(robust.sum())} из {int(reliable.sum())} reliable; причины отсева: {dict(Counter(r for r in reason if r and r != 'не reliable'))}")

    # ----- 10. персонажи
    costs = {}
    for r in read_csv("agent_costs.csv"):
        if r["system_id"] == cur_sys:
            costs[r["agent_id"]] = [float(r[f"c{i}"]) for i in range(7)]
    rarity = {r["agent_id"]: int(r["rarity"]) for r in read_csv("agents_meta.csv") if r["rarity"]} \
        if (DATA / "agents_meta.csv").exists() else {}
    agent_n = Counter(a for g in games for a in g["agents"])
    agent_rows = []
    for a in spec.agents:
        v = agent_vec(a)
        e = float(v @ beta) * ROOMS_PER_GAME
        eb = boots @ v * ROOMS_PER_GAME
        cost = costs.get(a, [None] * 7)[typical[a]]
        agent_rows.append({
            "agent_id": a, "name_en": names[a][0], "name_ru": names[a][1], "n_games": agent_n[a],
            "typical_mindscape": typical[a], "effect_sec_per_game": e,
            "ci_low": float(np.percentile(eb, 5)), "ci_high": float(np.percentile(eb, 95)),
            "effect_tobit": float(v @ tb) * ROOMS_PER_GAME, "effect_adjusted": float(v @ beta_adj),
            "current_cost": cost, "rarity": rarity.get(a),
        })

    # ----- 11. связки актуальной системы
    pair_set = set(spec.pairs)
    bundle_rows = []
    for b in bundles:
        ag = b["agents"]
        hits = [g for g in games if bundle_hit(g, ag, b["conds"])]
        n_games = len(hits)
        n_players = len({g["uid"] for g in hits})
        row = {"bundle": b, "n_games": n_games, "n_players": n_players, "status": "no_data"}
        v, partial = None, False
        if len(ag) == 2:
            p = tuple(ag)
            if p in pair_set:
                if b["conds"] is None:
                    v = Fd[pair_idx[p]].copy()
                elif n_games >= MIN_COND_GAMES:
                    cells = [(ca, cb) for ca in range(b["conds"][0][0], min(b["conds"][0][1], 6) + 1)
                             for cb in range(b["conds"][1][0], min(b["conds"][1][1], 6) + 1)]
                    wts = np.array([cell_w[(p, ca, cb)] for ca, cb in cells])
                    if wts.sum() > 0:
                        v = np.zeros(spec.p)
                        for (ca, cb), w_ in zip(cells, wts):
                            if w_ > 0:
                                v += w_ * Lc[pair_idx[p] * 49 + ca * 7 + cb].toarray().ravel()
                        v /= wts.sum()
        else:
            key = (ag, b["conds"])
            if key in spec.extra_col:
                subs = list(itertools.combinations(ag, 2))
                partial = not all(s_ in pair_set for s_ in subs)
                v = np.zeros(spec.p)
                for s_ in subs:
                    if s_ in pair_set:
                        v += Fd[pair_idx[s_]]
                v[spec.extra_col[key]] += 1
        if v is not None:
            e = float(v @ beta) * ROOMS_PER_GAME
            eb = boots @ v * ROOMS_PER_GAME
            row.update(status="ok", effect=e, lo=float(np.percentile(eb, 5)), hi=float(np.percentile(eb, 95)),
                       se=float(eb.std(ddof=1)), tobit=float(v @ tb) * ROOMS_PER_GAME,
                       adjusted=float(v @ beta_adj), partial=partial)
        bundle_rows.append(row)
    ok_rows = [r for r in bundle_rows if r["status"] == "ok"]
    pv = [2 * stats.norm.sf(abs(r["effect"] / r["se"])) if r["se"] > 0 else 1.0 for r in ok_rows]
    for r, q in zip(ok_rows, bh(pv) if ok_rows else []):
        r["q"] = float(q)
        r["reliable"] = bool((r["lo"] > 0 or r["hi"] < 0) and q <= BH_Q)
    for r in bundle_rows:
        r.setdefault("reliable", False)
    log(f"\n=== 10. Связки актуальной системы: всего {len(bundles)}, с оценкой {len(ok_rows)}, no_data "
        f"{sum(1 for r in bundle_rows if r['status'] == 'no_data')}, reliable {sum(r['reliable'] for r in bundle_rows)}; "
        f"условных двухперсонажных читаются из сетки: "
        f"{sum(1 for b in bundles if len(b['agents']) == 2 and b['conds'] is not None)}")

    # ----- 12. курсы
    log("\n=== 11. Курсы пересчёта в очки")

    def slope0(rows):
        best = {}
        for r in rows:
            k = (r["bundle"]["agents"], r["bundle"]["conds"])
            if k not in best or r["bundle"]["cost"] > best[k]["bundle"]["cost"]:
                best[k] = r
        pts = list(best.values())
        if not pts:
            return None, None, 0, []
        x = np.array([-r["effect"] for r in pts])
        yv = np.array([r["bundle"]["cost"] for r in pts])
        rt = float(x @ yv / (x @ x))
        s = float(np.sqrt(np.sum((yv - rt * x) ** 2) / (len(pts) - 1) / (x @ x))) if len(pts) > 1 else None
        return rt, s, len(pts), sorted((round(-r["effect"], 1), r["bundle"]["cost"]) for r in pts)

    rel = [r for r in ok_rows if r["reliable"]]
    rate_a, se_a, n_a_, pts_a = slope0(rel)
    if rate_a is not None:
        log(f"Курс А: {rate_a:.3f} очк/сек, SE {fmt(se_a, 3)}, точек {n_a_}; точки (-эффект, цена): {pts_a}")
    else:
        log("Курс А: нет ни одной связки с reliable-эффектом - курс не оценён")
    ag_c = [r for r in agent_rows if r["current_cost"] is not None]
    xs = np.array([r["current_cost"] for r in ag_c])
    ys = np.array([r["effect_sec_per_game"] for r in ag_c])
    sl = stats.linregress(xs, ys)
    rate_b = -sl.slope
    log(f"Курс Б: наклон {sl.slope:.3f} сек/игру на очко (SE {sl.stderr:.3f}), R^2 {sl.rvalue**2:.3f}, точек {len(ag_c)}; "
        f"курс Б = {rate_b:.3f} сек/очко")

    def rec_a(e):
        return None if rate_a is None else int(max(0, np.rint(-e * rate_a)))

    def rec_b(e):
        return int(max(0, np.rint(-e / rate_b))) if rate_b > 0 else None

    # ----- 13. таблицы пар
    cur_cost = {}
    bundle_cost = {}
    for b in bundles:
        if b["conds"] is None:
            bundle_cost[frozenset(b["agents"])] = max(bundle_cost.get(frozenset(b["agents"]), -1e9), b["cost"])
            if len(b["agents"]) == 2:
                cur_cost[b["agents"]] = max(cur_cost.get(b["agents"], -1e9), b["cost"])
    pst = pair_stats(games)
    pair_rows = []
    for i, p in enumerate(spec.pairs):
        top_uid, top_n = pair_players[p].most_common(1)[0]
        n_g, n_p = spec.pair_count[p]
        pair_rows.append({
            "agent_a": names[p[0]][0], "agent_b": names[p[1]][0], "agent_a_ru": names[p[0]][1],
            "agent_b_ru": names[p[1]][1], "n_games": n_g, "n_players": n_p,
            "effect_sec_per_game": pair_eff[i], "ci_low": lo[i], "ci_high": hi[i], "q_value": qval[i],
            "reliable": bool(reliable[i]), "effect_tobit": float(Fd[i] @ tb) * ROOMS_PER_GAME,
            "effect_adjusted": float(Fd[i] @ beta_adj), "current_cost": cur_cost.get(p),
            "rec_cost_a": rec_a(pair_eff[i]), "rec_cost_b": rec_b(pair_eff[i]),
            "top_player_share": top_n / n_g, "effect_wo_top_player": wo[(i, 1)],
            "p_b_given_a": pst[(p[0], p[1])]["p_half"], "p_a_given_b": pst[(p[1], p[0])]["p_half"],
            "top3_player_share": top3_share(pair_players[p], n_g),
            "effect_wo_top3": wo[(i, 3)], "robust": bool(robust[i]), "robust_note": reason[i],
        })
    pair_rows_sorted = sorted(pair_rows, key=lambda r: r["effect_sec_per_game"])
    pcols_out = ["agent_a", "agent_b", "agent_a_ru", "agent_b_ru", "n_games", "n_players", "effect_sec_per_game",
                 "ci_low", "ci_high", "q_value", "reliable", "effect_tobit", "effect_adjusted", "current_cost",
                 "rec_cost_a", "rec_cost_b", "top_player_share", "effect_wo_top_player", "p_b_given_a",
                 "p_a_given_b", "top3_player_share", "effect_wo_top3", "robust", "robust_note"]
    write_rows("pairs.csv", pcols_out, pair_rows_sorted)

    cb_rows = []
    for r in bundle_rows:
        b = r["bundle"]

        def cond_text(nm):
            return "; ".join((f"{n}: C{lo_}" if hi_ >= 6 else f"{n}: C{lo_}-C{hi_}")
                             for n, (lo_, hi_) in zip(nm, b["conds"]) if lo_ > 0 or hi_ < 6) if b["conds"] else ""
        ok = r["status"] == "ok"
        cb_rows.append({
            "bundle_id": b["id"], "agents": " + ".join(b["names"]), "conditions": cond_text(b["names"]),
            "agents_ru": " + ".join(b["names_ru"]), "conditions_ru": cond_text(b["names_ru"]),
            "required_tier": b["tier"], "current_cost": b["cost"], "n_games": r["n_games"],
            "n_players": r["n_players"], "effect_sec_per_game": r.get("effect"), "ci_low": r.get("lo"),
            "ci_high": r.get("hi"), "q_value": r.get("q"),
            "status": ("reliable" if r["reliable"] else "not_reliable") if ok else "no_data",
            "effect_tobit": r.get("tobit"), "effect_adjusted": r.get("adjusted"),
            "rec_cost_a": rec_a(r["effect"]) if ok else None, "rec_cost_b": rec_b(r["effect"]) if ok else None,
            "includes_pairs_below_threshold": r.get("partial"),
        })
    write_rows("current_bundles.csv",
               ["bundle_id", "agents", "conditions", "required_tier", "current_cost", "n_games", "n_players",
                "effect_sec_per_game", "ci_low", "ci_high", "q_value", "status", "effect_tobit", "effect_adjusted",
                "rec_cost_a", "rec_cost_b", "includes_pairs_below_threshold", "agents_ru", "conditions_ru"], cb_rows)
    write_rows("agents.csv",
               ["agent_id", "name_en", "name_ru", "n_games", "typical_mindscape", "effect_sec_per_game", "ci_low",
                "ci_high", "effect_tobit", "effect_adjusted", "current_cost", "rarity"],
               sorted(agent_rows, key=lambda r: r["effect_sec_per_game"]))

    # ----- 14. сетка созвездие x созвездие и уровни персонажей
    log(f"\n=== 12. Сетка созвездие x созвездие ({T()})")
    lam_loose = {**LAMF, "lm": min(LAMF["lm"], LAMF["lq"]), "lc": min(LAMF["lc"], LAMF["lq"])}
    pen_l = spec.pen(lam_loose)
    solver_cell_main = None
    sv_l = Solver(obs.X, obs.y, obs.w, pen_l, G=G)
    beta_l = sv_l.solve()[:, 0]
    del sv_l
    Mmat_l = Mmat.copy()
    shares_l = spec.shares(lam_loose)
    Mmat_l = Mmat_l.tolil()
    for key, ix in mem_idx.items():
        if key[0] == "pair":
            p = (key[1], key[2])
            m_ = (p, key[3], key[4])
            col = spec.pair_feat_col[m_]
            Mmat_l[ix, col] = shares_l[m_]
        elif key[0] == "lvl":
            m_ = (key[1], key[2])
            Mmat_l[ix, spec.lvl_col[m_]] = shares_l[m_]
    Mmat_l = Mmat_l.tocsr()
    Lc_l, La_l = build_levels_cells(Mmat_l)
    log(f"вариант loose: λ поправок уровня {lam_loose['lm']}, ячейки {lam_loose['lc']} (основной: {LAMF['lm']}, {LAMF['lc']})")

    syn = (Lc @ beta) * ROOMS_PER_GAME
    syn_b = (Lc @ boots.T) * ROOMS_PER_GAME
    lvl_b = (La @ boots.T) * ROOMS_PER_GAME
    lvl = (La @ beta) * ROOMS_PER_GAME
    syn_l = (Lc_l @ beta_l) * ROOMS_PER_GAME
    lvl_l = (La_l @ beta_l) * ROOMS_PER_GAME
    grid_rows = []
    status_count = Counter()
    measured_per_pair = np.zeros(len(spec.pairs), int)
    for ip, p in enumerate(spec.pairs):
        ia, ib = agent_idx[p[0]], agent_idx[p[1]]
        for ca in range(7):
            for cb in range(7):
                r = ip * 49 + ca * 7 + cb
                n_g_ = cell_n[(p, ca, cb)]
                n_p_ = len(cell_pl[(p, ca, cb)])
                st = "measured" if n_g_ >= CELL_MEASURED_GAMES and n_p_ >= CELL_MEASURED_PLAYERS else \
                    ("thin" if n_g_ > 0 else "extrapolated")
                status_count[st] += 1
                measured_per_pair[ip] += st == "measured"
                ra, rb = ia * 7 + ca, ib * 7 + cb
                tot_b = syn_b[r] + lvl_b[ra] + lvl_b[rb]
                grid_rows.append({
                    "agent_a": names[p[0]][0], "agent_b": names[p[1]][0], "agent_a_ru": names[p[0]][1],
                    "agent_b_ru": names[p[1]][1], "ca": ca, "cb": cb, "n_games": n_g_, "n_players": n_p_,
                    "weight_sum": float(cell_w[(p, ca, cb)]), "synergy_effect": float(syn[r]),
                    "ci_low": float(np.percentile(syn_b[r], 5)), "ci_high": float(np.percentile(syn_b[r], 95)),
                    "total_effect": float(syn[r] + lvl[ra] + lvl[rb]),
                    "total_ci_low": float(np.percentile(tot_b, 5)), "total_ci_high": float(np.percentile(tot_b, 95)),
                    "synergy_loose": float(syn_l[r]), "total_loose": float(syn_l[r] + lvl_l[ra] + lvl_l[rb]),
                    "status": st,
                })
    write_rows("pair_const_grid.csv",
               ["agent_a", "agent_b", "agent_a_ru", "agent_b_ru", "ca", "cb", "n_games", "n_players", "weight_sum",
                "synergy_effect", "ci_low", "ci_high", "total_effect", "total_ci_low", "total_ci_high",
                "synergy_loose", "total_loose", "status"], grid_rows)
    n_cells = len(grid_rows)
    log(f"ячеек {n_cells}: measured {status_count['measured']}, thin {status_count['thin']}, "
        f"extrapolated {status_count['extrapolated']}; пар с measured >= 2 ячеек: {int((measured_per_pair >= 2).sum())} "
        f"из {len(spec.pairs)}, с >= 1: {int((measured_per_pair >= 1).sum())}")
    sd_syn = np.std(syn)
    log(f"синергия по ячейкам: sd {sd_syn:.1f} с/игру; в loose sd {np.std(syn_l):.1f}; основной vs loose, корреляция "
        f"{np.corrcoef(syn, syn_l)[0, 1]:.3f}")
    # вклад поправок сетки: разброс эффекта пары между measured-ячейками одной пары
    spread = []
    for ip, p in enumerate(spec.pairs):
        ms = [syn[ip * 49 + ca * 7 + cb] for ca in range(7) for cb in range(7)
              if cell_n[(p, ca, cb)] >= CELL_MEASURED_GAMES and len(cell_pl[(p, ca, cb)]) >= CELL_MEASURED_PLAYERS]
        if len(ms) >= 2:
            spread.append(max(ms) - min(ms))
    log(f"размах синергии между measured-ячейками одной пары (основной расчёт): медиана {np.median(spread):.1f}, "
        f"максимум {np.max(spread):.1f} с/игру (пар {len(spread)})" if spread else "размах: нет пар с >= 2 measured-ячеек")

    # уровни персонажей
    ac_rows = []
    lvl_games = Counter()
    lvl_players = defaultdict(set)
    for g in games:
        for a in g["agents"]:
            lvl_games[(a, g["lv"][a])] += 1
            lvl_players[(a, g["lv"][a])].add(g["uid"])
    for a in spec.agents:
        ia = agent_idx[a]
        for c in range(7):
            n_g_, n_p_ = lvl_games[(a, c)], len(lvl_players[(a, c)])
            st = "measured" if n_g_ >= CELL_MEASURED_GAMES and n_p_ >= CELL_MEASURED_PLAYERS else \
                ("thin" if n_g_ > 0 else "extrapolated")
            r = ia * 7 + c
            cost = costs.get(a, [None] * 7)[c]
            c0 = costs.get(a, [None] * 7)[0]
            step = None if cost is None or c0 is None else cost - c0
            ac_rows.append({
                "agent_id": a, "name_en": names[a][0], "name_ru": names[a][1], "level": c, "n_games": n_g_,
                "n_players": n_p_, "effect_vs_c0": float(lvl[r]),
                "ci_low": float(np.percentile(lvl_b[r], 5)), "ci_high": float(np.percentile(lvl_b[r], 95)),
                "current_cost": cost, "cost_step_vs_c0": step,
                "cost_implied_effect": None if step is None or rate_b <= 0 else -step * rate_b,
                "status": st, "rarity": rarity.get(a),
            })
    write_rows("agent_const.csv",
               ["agent_id", "name_en", "name_ru", "level", "n_games", "n_players", "effect_vs_c0", "ci_low", "ci_high",
                "current_cost", "cost_step_vs_c0", "cost_implied_effect", "status", "rarity"], ac_rows)
    ac_status = Counter(r["status"] for r in ac_rows)
    log(f"уровни персонажей: {len(ac_rows)} строк: measured {ac_status['measured']}, thin {ac_status['thin']}, "
        f"extrapolated {ac_status['extrapolated']}")
    div = [r for r in ac_rows if r["status"] == "measured" and r["level"] > 0 and r["cost_implied_effect"] is not None]
    div.sort(key=lambda r: -abs(r["effect_vs_c0"] - r["cost_implied_effect"]))
    log("Сильнее всего расходятся с шагом цены (измеренные уровни; эффект против эффекта, подразумеваемого шагом цены по курсу Б):")
    for r in div[:8]:
        log(f"  {r['name_en']} C{r['level']}: n={r['n_games']}/{r['n_players']}, эффект {r['effect_vs_c0']:.1f} "
            f"[{r['ci_low']:.1f}; {r['ci_high']:.1f}], шаг цены {r['cost_step_vs_c0']:.0f} -> подразумевает "
            f"{r['cost_implied_effect']:.1f}")

    # ----- 15. неразлучные
    log(f"\n=== 13. Неразлучные персонажи ({T()})")
    insep_rows = []
    for (a, b), st in sorted(spec.insep.items(), key=lambda kv: -kv[1]["n_a"]):
        kind = "half" if st["p_half"] >= INSEP_SHARE else "draft"
        p = tuple(sorted((a, b)))
        va = agent_vec(a)
        ea = float(va @ beta) * ROOMS_PER_GAME
        eab = boots @ va * ROOMS_PER_GAME
        row = {"agent_a": names[a][0], "agent_b": names[b][0], "agent_a_ru": names[a][1], "agent_b_ru": names[b][1],
               "kind": kind, "n_a": st["n_a"], "n_players_a": st["players_a"], "p_same_half": st["p_half"],
               "p_same_draft": st["p_draft"], "n_pair_games": st["n_half"],
               "n_pair_players": spec.pair_count.get(p, (0, 0))[1],
               "agent_effect": ea, "agent_ci_low": float(np.percentile(eab, 5)),
               "agent_ci_high": float(np.percentile(eab, 95)),
               "typical_mindscape_a": typical[a], "rarity_a": rarity.get(a),
               "cost_a": costs.get(a, [None] * 7)[typical[a]], "bundle_cost": bundle_cost.get(frozenset(p)),
               "note": "по отдельности ненадёжны: эффект персонажа и пары данными не разделяются"}
        if p in pair_idx:
            fp = Fd[pair_idx[p]]
            ep = float(fp @ beta) * ROOMS_PER_GAME
            epb = boots @ fp * ROOMS_PER_GAME
            row.update(pair_effect=ep, pair_ci_low=float(np.percentile(epb, 5)),
                       pair_ci_high=float(np.percentile(epb, 95)), pair_in_model="основная",
                       boot_corr_agent_pair=float(np.corrcoef(eab, epb)[0, 1]))
            if kind == "half":
                vu = va + fp
                eu = float(vu @ beta) * ROOMS_PER_GAME
                eub = boots @ vu * ROOMS_PER_GAME
                row.update(unit_effect=eu, unit_ci_low=float(np.percentile(eub, 5)),
                           unit_ci_high=float(np.percentile(eub, 95)), rec_cost_a=rec_a(eu), rec_cost_b=rec_b(eu))
                if row["cost_a"] is not None:
                    row["current_unit_cost"] = row["cost_a"] + (row["bundle_cost"] or 0)
        insep_rows.append(row)
    write_rows("inseparable.csv",
               ["agent_a", "agent_b", "agent_a_ru", "agent_b_ru", "kind", "n_a", "n_players_a", "p_same_half",
                "p_same_draft", "n_pair_games", "n_pair_players", "unit_effect", "unit_ci_low", "unit_ci_high",
                "agent_effect", "agent_ci_low", "agent_ci_high", "pair_effect", "pair_ci_low", "pair_ci_high",
                "boot_corr_agent_pair", "pair_in_model", "typical_mindscape_a", "rarity_a", "cost_a", "bundle_cost",
                "current_unit_cost", "rec_cost_a", "rec_cost_b", "note"], insep_rows)
    log(f"неразлучных упорядоченных пар: {len(insep_rows)}")
    for r in insep_rows:
        log(f"  [{r['kind']}] {r['agent_a']} -> {r['agent_b']}: n_a={r['n_a']} p_half={r['p_same_half']:.2f} "
            f"unit={fmt(r.get('unit_effect'))} [{fmt(r.get('unit_ci_low'))}; {fmt(r.get('unit_ci_high'))}] "
            f"агент {r['agent_effect']:.1f} пара {fmt(r.get('pair_effect'))}")

    # ----- 16. команды
    log(f"\n=== 14. Команды (четвёрки) ({T()})")
    tc = defaultdict(lambda: {"pl": Counter(), "games": []})
    for gi, g in enumerate(games):
        for h in g["half"]:
            tc[h]["pl"][g["uid"]] += 1
            tc[h]["games"].append(gi)
    teams = {h: t for h, t in tc.items() if len(t["games"]) >= MIN_TEAM_GAMES and len(t["pl"]) >= MIN_TEAM_PLAYERS}
    log(f"четвёрок в играх: {len(tc)}, с >= {MIN_TEAM_GAMES} игрок-игр и >= {MIN_TEAM_PLAYERS} игроков: {len(teams)}")
    pen_np = spec.pen(variant_lam("nopairs", best_np))
    solver_np = Solver(obs.X, obs.y, obs.w, pen_np, G=G, keep=pen_np < 1e9)
    b_np = solver_np.solve()[:, 0]
    res_obs = obs.y - obs.X @ b_np
    cnt_g = np.bincount(obs.gi, minlength=len(games))
    resid_game = np.bincount(obs.gi, weights=res_obs, minlength=len(games)) / np.maximum(cnt_g, 1) * ROOMS_PER_GAME
    log(f"остатки модели без пар: RMSE на комнату {np.sqrt(np.mean(res_obs ** 2)):.3f}")
    fold = fold_assign(obs, SEED)
    gfold = np.zeros(len(games), int)
    gfold[obs.gi] = fold
    W5 = obs.w[:, None] * (fold[:, None] != np.arange(N_FOLDS)[None, :])
    B_full5, B_np5 = solver.solve(W5), solver_np.solve(W5)
    rows_all = np.arange(len(obs.y))
    pred_np5 = np.asarray(obs.X @ B_np5)[rows_all, fold]
    r_oof = obs.y - pred_np5
    oof_resid = np.bincount(obs.gi, weights=r_oof, minlength=len(games)) / np.maximum(cnt_g, 1) * ROOMS_PER_GAME
    fold_coefs = []
    for k in range(N_FOLDS):
        ck = Coefs(mem_keys, Mmat @ B_full5[:, k], names, typical)
        ck.baseline = coefs.baseline
        fold_coefs.append(ck)
    del solver_np

    team_rows = []
    for h, t in teams.items():
        ids = sorted(h)
        score = team_breakdown(coefs, h, None)
        pp = score["parts"]
        gl = t["games"]
        act = np.mean([float(((coefs.vector(h, games[gi]["lv"])[0] - coefs.baseline) * coefs.vec).sum())
                       for gi in gl]) * ROOMS_PER_GAME
        oo_pair, oo_bey = [], []
        for gi in gl:
            ck = fold_coefs[gfold[gi]]
            w_ = ck.vector(h, games[gi]["lv"])[0] * ck.vec * ROOMS_PER_GAME
            oo_pair.append(w_[ck.group == "pair"].sum())
            oo_bey.append(w_[np.isin(ck.group, ("pair", "const", "extra"))].sum())
        cost_ag = [costs.get(a, [None] * 7)[typical.get(a, 0)] for a in ids]
        cost_bu = sum(c for k_, c in bundle_cost.items() if k_ <= h)
        cost = None if any(c is None for c in cost_ag) else float(sum(cost_ag) + cost_bu)
        order_ = sorted(ids, key=lambda a: names[a][0])
        team_rows.append({
            "team_en": " + ".join(names[a][0] for a in order_), "team_ru": " + ".join(names[a][1] for a in order_),
            "n_games": len(gl), "n_players": len(t["pl"]), "top3_player_share": top3_share(t["pl"], len(gl)),
            "predicted_effect": score["effect"], "ci_low": score["ci"][0], "ci_high": score["ci"][1],
            "contrib_agents": pp["agent"], "contrib_pairs": pp["pair"], "contrib_const": pp["const"],
            "contrib_extra": pp["extra"], "n_pairs_unestimated": score["n_pairs_unestimated"],
            "observed_resid": float(np.mean(resid_game[gl])), "predicted_actual_mind": act,
            "oof_pairs": float(np.mean(oo_pair)), "oof_beyond": float(np.mean(oo_bey)),
            "oof_resid": float(np.mean(oof_resid[gl])),
            "cost_team": cost, "cost_agents": None if cost is None else float(sum(cost_ag)),
            "cost_bundles": cost_bu, "sec_per_point": score["effect"] / cost if cost else None})
    team_rows.sort(key=lambda r: r["predicted_effect"])
    write_rows("teams.csv",
               ["team_en", "team_ru", "n_games", "n_players", "top3_player_share", "predicted_effect", "ci_low",
                "ci_high", "contrib_agents", "contrib_pairs", "contrib_const", "contrib_extra", "n_pairs_unestimated",
                "observed_resid", "predicted_actual_mind", "oof_pairs", "oof_beyond", "oof_resid", "cost_team",
                "cost_agents", "cost_bundles", "sec_per_point"], team_rows)

    def tcorr(xk, yk):
        return corr(np.array([r[xk] for r in team_rows]), np.array([r[yk] for r in team_rows]))

    check_corr = {
        "pairs_vs_resid": tcorr("contrib_pairs", "observed_resid"),
        "beyond_vs_resid": corr(np.array([r["contrib_pairs"] + r["contrib_const"] + r["contrib_extra"] for r in team_rows]),
                                np.array([r["observed_resid"] for r in team_rows])),
        "oof_pairs_vs_oof_resid": tcorr("oof_pairs", "oof_resid"),
        "oof_beyond_vs_oof_resid": tcorr("oof_beyond", "oof_resid"),
        "agents_vs_resid": tcorr("contrib_agents", "observed_resid"),
    }
    log(f"корреляция (Пирсон, Спирмен) по {len(team_rows)} командам: вклад пар x остаток без пар: "
        f"{check_corr['pairs_vs_resid'][0]:.3f}, {check_corr['pairs_vs_resid'][1]:.3f}; пары+поправки+связки: "
        f"{check_corr['beyond_vs_resid'][0]:.3f}, {check_corr['beyond_vs_resid'][1]:.3f}")
    log(f"  вне подгонки (по турнирам): вклад пар x остаток {check_corr['oof_pairs_vs_oof_resid'][0]:.3f}, "
        f"{check_corr['oof_pairs_vs_oof_resid'][1]:.3f}; пары+поправки+связки {check_corr['oof_beyond_vs_oof_resid'][0]:.3f}, "
        f"{check_corr['oof_beyond_vs_oof_resid'][1]:.3f}; вклад персонажей x остаток {check_corr['agents_vs_resid'][0]:.3f}")

    def tline(r):
        return (f"{r['team_en']}: n={r['n_games']}/{r['n_players']} топ3 {r['top3_player_share']:.0%} "
                f"pred {r['predicted_effect']:.1f} [{r['ci_low']:.1f}; {r['ci_high']:.1f}] resid {r['observed_resid']:.1f} "
                f"стоимость {fmt(r['cost_team'], 0)} с/очко {fmt(r['sec_per_point'], 2)}")
    log("Топ-5 самых быстрых команд:")
    for r in team_rows[:5]:
        log("  " + tline(r))

    # ----- 17. сравнение с v2 и итоговые проверки
    v2p = RES.parent / "results_v2" / "pairs.csv"
    cmp_ = {}
    if v2p.exists():
        v2 = {r["agent_a"] + "|" + r["agent_b"]: r for r in read_csv_path(v2p)}
        new_ = {r["agent_a"] + "|" + r["agent_b"]: r for r in pair_rows}
        keys_ = [k for k in new_ if k in v2]
        x = np.array([float(v2[k]["effect_sec_per_game"]) for k in keys_])
        y = np.array([new_[k]["effect_sec_per_game"] for k in keys_])
        was_rel = [k for k in keys_ if v2[k]["reliable"] == "True"]
        still_rel = [k for k in was_rel if new_[k]["reliable"]]
        new_rel = [k for k in keys_ if new_[k]["reliable"] and v2[k]["reliable"] != "True"]
        lost = [(k, new_[k]["robust_note"]) for k in was_rel if not new_[k]["robust"]]
        cmp_ = {"n": len(keys_), "pearson": float(np.corrcoef(x, y)[0, 1]), "spearman": float(stats.spearmanr(x, y)[0]),
                "max_abs_shift": float(np.abs(y - x).max()), "mean_abs_shift": float(np.abs(y - x).mean()),
                "n_reliable_v2": len(was_rel), "still_reliable": len(still_rel), "new_reliable": len(new_rel),
                "n_reliable_now": int(reliable.sum()), "n_robust_now": int(robust.sum()),
                "robust_of_v2_reliable": sum(1 for k in was_rel if new_[k]["robust"]),
                "dropped": [{"pair": k.replace("|", " + "), "reason": why or "robust"} for k, why in lost],
                "dropped_reasons": dict(Counter(why for _, why in lost))}
        log(f"\n=== 15. Сравнение с v2: {len(keys_)} общих пар, корреляция заголовочных эффектов Пирсон "
            f"{cmp_['pearson']:.3f}, Спирмен {cmp_['spearman']:.3f}, средний |сдвиг| {cmp_['mean_abs_shift']:.1f}, "
            f"максимальный {cmp_['max_abs_shift']:.1f}; reliable в v2 {cmp_['n_reliable_v2']}, из них остались reliable "
            f"{cmp_['still_reliable']}, стали robust {cmp_['robust_of_v2_reliable']}; новых reliable {cmp_['new_reliable']}; "
            f"reliable сейчас {cmp_['n_reliable_now']}, robust {cmp_['n_robust_now']}")
        log(f"  выпали из числа robust: причины {cmp_['dropped_reasons']}")
    checks = {"n_pairs": len(spec.pairs), "n_reliable": int(reliable.sum()), "n_robust": int(robust.sum()),
              "n_games": len(games), "n_players": len(spec.players), "weight_cap": WEIGHT_CAP,
              "lam": LAMF, "lam_nogrid": {k: best_ng[k] for k in FREE["nogrid"]},
              "lam_nopairs": {k: best_np[k] for k in FREE["nopairs"]}, "lam_loose": lam_loose,
              "cv": {"full": list(m_full), "nogrid": list(m_ng), "nopairs": list(m_np)},
              "holdout": holdout, "holdout_diff": {k: list(v) for k, v in holdout_diff.items()},
              "stability_pearson": stab_corr, "share_negative_pairs": float(np.mean(pair_eff < 0)),
              "n_cells": n_cells, "cell_status": dict(status_count), "pairs_measured_ge2": int((measured_per_pair >= 2).sum()),
              "agent_const_status": dict(ac_status), "n_teams": len(team_rows), "n_insep": len(insep_rows),
              "team_corr": {k: list(v) for k, v in check_corr.items()}, "v2_comparison": cmp_}
    (RES / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")

    log("\n=== Топ-15 robust-пар (сек/игру, меньше - быстрее)")
    for r in [r for r in pair_rows_sorted if r["robust"]][:15]:
        log(f"  {r['agent_a']} + {r['agent_b']}: n={r['n_games']}/{r['n_players']} {r['effect_sec_per_game']:.1f} "
            f"[{r['ci_low']:.1f}; {r['ci_high']:.1f}] без топ-3 {fmt(r['effect_wo_top3'])} q={r['q_value']:.3f}")
    log(f"\nготово за {time.time() - t0:.0f} с; файлы в {RES}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Модель связок; без аргументов - полный пересчёт.")
    ap.add_argument("--score", help='оценить четвёрку по сохранённым коэффициентам: "A,B,C,D" (имена en)')
    ap.add_argument("--mind", help='созвездия для --score: "A=6,B=2" (остальные - типичные)')
    ap.add_argument("--reuse-lam", action="store_true", help="взять штрафы из data/results/lam_cache.json")
    args = ap.parse_args()
    if args.score:
        cli_score(args.score, args.mind)
        sys.exit(0)
    sys.exit(main())
