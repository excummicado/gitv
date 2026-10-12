#!/usr/bin/env node
// Сбор статистики игроков из выгрузок API матчей (items[] с drafts[]).
//
// Использование:
//   node draft-stats.mjs <файлы или папки с .json ...> [--names names.json] [--out ./out]
//   node draft-stats.mjs --urls tournaments-url.txt [--data ./data] [--header "Authorization: ..."]
//
// --urls скачивает каждую ссылку из файла (limit=100000000000) в --data и сразу строит отчёт.
//
// Каждый входной файл — ответ API вида { items: [...], count } (или просто массив матчей).
// Матчи с одинаковым _id из разных файлов учитываются один раз.
//
// names.json (необязательно) — названия агентов и движков:
//   { "agents": { "<id>": "Имя" }, "engines": { "<id>": "Имя" } }
//   или { "agents": [{ "_id": "...", "name": "..." }], "engines": [...] }

import fs from 'node:fs';
import path from 'node:path';

// ---------- аргументы ----------
const LIMIT = '100000000000';
const argv = process.argv.slice(2);
const inputs = [];
let namesFile = null;
let outDir = './out';
let urlsFile = null;
let dataDir = './data';
const headers = {};
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--names') namesFile = argv[++i];
  else if (argv[i] === '--out') outDir = argv[++i];
  else if (argv[i] === '--urls') urlsFile = argv[++i];
  else if (argv[i] === '--data') dataDir = argv[++i];
  else if (argv[i] === '--header') {
    const h = argv[++i];
    const k = h.indexOf(':');
    headers[h.slice(0, k).trim()] = h.slice(k + 1).trim();
  } else inputs.push(argv[i]);
}
if (urlsFile) {
  await downloadAll(urlsFile, dataDir);
  inputs.push(dataDir);
}
if (!inputs.length) {
  console.error('Usage: node draft-stats.mjs <files|dirs...> [--urls urls.txt] [--data dir] [--header "K: V"] [--names names.json] [--out dir]');
  process.exit(1);
}

// ---------- загрузка по ссылкам ----------
// Каждая строка файла — ссылка на API матчей. limit заменяется на огромный, чтобы забрать всё одним запросом;
// если сервер всё равно отдал меньше, чем count, докачиваем страницами через skip/offset/page, если они есть в ссылке.
async function fetchJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json', ...headers } });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText} — ${url}`);
  return res.json();
}

async function downloadAll(file, dir) {
  const urls = fs.readFileSync(file, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#'));
  fs.mkdirSync(dir, { recursive: true });
  for (const [n, raw] of urls.entries()) {
    const url = new URL(raw);
    url.searchParams.set('limit', LIMIT);
    const tag = `[${n + 1}/${urls.length}]`;
    try {
      const first = await fetchJson(url);
      const items = Array.isArray(first) ? first : [...(first.items ?? [])];
      const count = first.count ?? items.length;

      const pageKey = ['skip', 'offset', 'page'].find(k => url.searchParams.has(k));
      while (items.length < count && pageKey) {
        const before = items.length;
        const next = new URL(url);
        if (pageKey === 'page') next.searchParams.set('page', String(Number(url.searchParams.get('page') || 1) + 1));
        else next.searchParams.set(pageKey, String(Number(url.searchParams.get(pageKey) || 0) + items.length));
        if (pageKey === 'page') url.searchParams.set('page', next.searchParams.get('page'));
        const page = await fetchJson(next);
        items.push(...(Array.isArray(page) ? page : page.items ?? []));
        if (items.length === before) break;
      }
      if (items.length < count) console.warn(`${tag} получено ${items.length} из ${count} матчей — сервер урезал лимит`);

      const out = path.join(dir, `${String(n + 1).padStart(3, '0')}.json`);
      fs.writeFileSync(out, JSON.stringify({ source: raw, items, count }));
      console.log(`${tag} ${items.length}/${count} матчей → ${out}`);
    } catch (e) {
      console.error(`${tag} ошибка: ${e.message}`);
    }
  }
}

// ---------- загрузка ----------
function listJson(p) {
  const st = fs.statSync(p);
  if (!st.isDirectory()) return [p];
  return fs.readdirSync(p).filter(f => f.endsWith('.json')).map(f => path.join(p, f));
}

function toMap(v) {
  if (!v) return {};
  if (Array.isArray(v)) return Object.fromEntries(v.map(x => [x._id, x.name ?? x.title ?? x.nameEn ?? x._id]));
  return v;
}
const names = namesFile ? JSON.parse(fs.readFileSync(namesFile, 'utf8')) : {};
const agentNames = toMap(names.agents);
const engineNames = toMap(names.engines);
const agentName = id => agentNames[id] ?? `agent:${id.slice(-6)}`;
const engineName = id => engineNames[id] ?? `engine:${id.slice(-6)}`;

const matchesById = new Map();
for (const input of inputs) {
  for (const file of listJson(input)) {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    const items = Array.isArray(data) ? data : data.items ?? [];
    for (const m of items) if (m?._id && m.drafts) matchesById.set(m._id, m);
  }
}

// ---------- правила ----------
// Предположение: штрафные рестарты добавляют секунды к clearTime.
// freeRestarts бесплатны, далее каждый следующий стоит paidRestarts[k] (последнее значение повторяется).
function adjustedTime(player, phaseMatch) {
  const free = phaseMatch?.freeRestarts ?? 0;
  const paid = phaseMatch?.paidRestarts ?? [];
  let t = player.clearTime;
  for (let k = 0; k < player.restarts - free; k++) t += paid[Math.min(k, paid.length - 1)] ?? 0;
  return t;
}

// ---------- нормализация игр ----------
const games = [];   // одна запись на драфт (игру)
const matches = []; // одна запись на матч

const sortedMatches = [...matchesById.values()].sort((a, b) => a.createdAt.localeCompare(b.createdAt));
for (const m of sortedMatches) {
  // users[i] соответствует drafts[0].players[i]; дальше сопоставляем по имени
  const nameToUser = {};
  m.drafts[0].players.forEach((p, i) => { nameToUser[p.fullName] = m.users?.[i] ?? p.fullName; });

  const matchGames = [];
  m.drafts.forEach((d, gi) => {
    if (d.status !== 'FINISHED') return;
    const players = d.players.map(p => ({
      userId: nameToUser[p.fullName] ?? p.fullName,
      name: p.fullName,
      clearTime: p.clearTime,
      time: adjustedTime(p, m.system?.phaseMatch),
      restarts: p.restarts,
      picks: p.teams.filter(t => t.agent.agent).map(t => ({
        agent: t.agent.agent, mindscape: t.agent.mindscape, level: t.agent.level,
        engine: t.engine.engine, refinement: t.engine.refinement,
      })),
    }));
    const [a, b] = players;
    const winner = a.time === b.time ? null : (a.time < b.time ? a.userId : b.userId);
    const g = {
      matchId: m._id, draftId: d._id, gameNo: gi + 1,
      tournament: m.tournament?.title ?? '', tournamentId: m.tournament?._id ?? '',
      date: m.createdAt, firstPick: players[d.pIndex?.[0] ?? 0]?.userId,
      players, winner,
    };
    games.push(g);
    matchGames.push(g);
  });
  if (!matchGames.length) continue;

  // Итог матча: сумма скорректированного времени по сыгранным играм
  const totals = {};
  for (const g of matchGames) for (const p of g.players) totals[p.userId] = (totals[p.userId] ?? 0) + p.time;
  const [u1, u2] = Object.keys(totals);
  const complete = matchGames.length === m.drafts.length;
  const winner = !complete || totals[u1] === totals[u2] ? null : (totals[u1] < totals[u2] ? u1 : u2);
  matches.push({
    matchId: m._id, tournament: m.tournament?.title ?? '', date: m.createdAt,
    complete, totals, winner, games: matchGames,
  });
}

// ---------- агрегаты по игрокам ----------
const players = new Map();
function getPlayer(userId, name) {
  if (!players.has(userId)) players.set(userId, {
    userId, name, names: new Set(),
    matches: 0, matchWins: 0, matchLosses: 0, matchDraws: 0,
    games: 0, gameWins: 0, gameLosses: 0, gameDraws: 0,
    times: [], rawTimes: [], restarts: 0, restartsList: [],
    agents: {}, engines: {}, opponents: {}, tournaments: new Set(), log: [],
  });
  const p = players.get(userId);
  p.name = name; // последнее известное имя (данные отсортированы по дате)
  p.names.add(name);
  return p;
}

for (const g of games) {
  for (const me of g.players) {
    const opp = g.players.find(x => x !== me);
    const p = getPlayer(me.userId, me.name);
    p.games++;
    p.tournaments.add(g.tournament);
    const res = g.winner === null ? 'D' : g.winner === me.userId ? 'W' : 'L';
    if (res === 'W') p.gameWins++; else if (res === 'L') p.gameLosses++; else p.gameDraws++;
    p.times.push(me.time);
    p.rawTimes.push(me.clearTime);
    p.restarts += me.restarts;
    for (const pk of me.picks) {
      const a = p.agents[pk.agent] ??= { games: 0, wins: 0, mindscapes: [] };
      a.games++; if (res === 'W') a.wins++; a.mindscapes.push(pk.mindscape);
      const e = p.engines[pk.engine] ??= { games: 0, wins: 0 };
      e.games++; if (res === 'W') e.wins++;
    }
    const h = p.opponents[opp.userId] ??= { name: opp.name, games: 0, gameWins: 0, matches: 0, matchWins: 0 };
    h.name = opp.name; h.games++; if (res === 'W') h.gameWins++;
    p.log.push({
      date: g.date, tournament: g.tournament, matchId: g.matchId, draftId: g.draftId, game: g.gameNo,
      opponent: opp.name, result: res, time: me.time, clearTime: me.clearTime, restarts: me.restarts,
      oppTime: opp.time, firstPick: g.firstPick === me.userId,
      team: me.picks.map(pk => `${agentName(pk.agent)} M${pk.mindscape} + ${engineName(pk.engine)} R${pk.refinement}`),
    });
  }
}
for (const m of matches) {
  for (const uid of Object.keys(m.totals)) {
    const p = players.get(uid);
    const opp = Object.keys(m.totals).find(x => x !== uid);
    if (!m.complete) continue;
    p.matches++;
    p.opponents[opp].matches++;
    if (m.winner === null) p.matchDraws++;
    else if (m.winner === uid) { p.matchWins++; p.opponents[opp].matchWins++; }
    else p.matchLosses++;
  }
}

// ---------- глобальная статистика агентов ----------
const totalTeams = games.length * 2; // сколько раз вообще собирался состав
const agentGlobal = {};
for (const g of games) for (const me of g.players) {
  const res = g.winner === me.userId;
  for (const id of new Set(me.picks.map(x => x.agent))) {
    const a = agentGlobal[id] ??= { picks: 0, wins: 0, players: new Set() };
    a.picks++; if (res) a.wins++; a.players.add(me.userId);
  }
}

// ---------- вывод ----------
const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : 0);
const avg = arr => (arr.length ? Math.round(arr.reduce((s, x) => s + x, 0) / arr.length * 10) / 10 : 0);

const playerStats = [...players.values()].map(p => ({
  userId: p.userId,
  name: p.name,
  aliases: [...p.names],
  tournaments: [...p.tournaments],
  matches: p.matches, matchWins: p.matchWins, matchLosses: p.matchLosses, matchDraws: p.matchDraws,
  matchWinrate: pct(p.matchWins, p.matches),
  games: p.games, gameWins: p.gameWins, gameLosses: p.gameLosses, gameDraws: p.gameDraws,
  gameWinrate: pct(p.gameWins, p.games),
  avgTime: avg(p.times), bestTime: Math.min(...p.times), worstTime: Math.max(...p.times),
  avgClearTime: avg(p.rawTimes),
  totalRestarts: p.restarts, avgRestarts: Math.round(p.restarts / p.games * 100) / 100,
  agents: Object.entries(p.agents)
    .map(([id, a]) => ({ id, name: agentName(id), games: a.games, pickrate: pct(a.games, p.games),
      winrate: pct(a.wins, a.games), avgMindscape: avg(a.mindscapes) }))
    .sort((x, y) => y.games - x.games || y.winrate - x.winrate),
  engines: Object.entries(p.engines)
    .map(([id, e]) => ({ id, name: engineName(id), games: e.games, pickrate: pct(e.games, p.games), winrate: pct(e.wins, e.games) }))
    .sort((x, y) => y.games - x.games),
  opponents: Object.entries(p.opponents)
    .map(([id, o]) => ({ userId: id, name: o.name, matches: o.matches, matchWins: o.matchWins,
      games: o.games, gameWins: o.gameWins, gameWinrate: pct(o.gameWins, o.games) }))
    .sort((x, y) => y.games - x.games),
  log: p.log,
})).sort((a, b) => b.matchWinrate - a.matchWinrate || b.gameWinrate - a.gameWinrate || b.games - a.games);

const agentStats = Object.entries(agentGlobal).map(([id, a]) => ({
  id, name: agentName(id), picks: a.picks, pickrate: pct(a.picks, totalTeams),
  winrate: pct(a.wins, a.picks), players: a.players.size,
})).sort((x, y) => y.picks - x.picks);

fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'stats.json'), JSON.stringify({
  generatedAt: new Date().toISOString(),
  summary: { matches: matches.length, games: games.length, players: playerStats.length },
  players: playerStats, agents: agentStats,
}, null, 2));

const csvCell = v => { const s = String(v ?? ''); return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
const toCsv = rows => rows.length
  ? [Object.keys(rows[0]).join(','), ...rows.map(r => Object.values(r).map(csvCell).join(','))].join('\n') + '\n' : '';

fs.writeFileSync(path.join(outDir, 'players.csv'), toCsv(playerStats.map(p => ({
  name: p.name, userId: p.userId, matches: p.matches, matchWins: p.matchWins, matchWinrate: p.matchWinrate,
  games: p.games, gameWins: p.gameWins, gameWinrate: p.gameWinrate, avgTime: p.avgTime, bestTime: p.bestTime,
  avgRestarts: p.avgRestarts, topAgents: p.agents.slice(0, 5).map(a => `${a.name} (${a.games})`).join(' | '),
}))));

fs.writeFileSync(path.join(outDir, 'games.csv'), toCsv(playerStats.flatMap(p => p.log.map(l => ({
  player: p.name, date: l.date, tournament: l.tournament, matchId: l.matchId, draftId: l.draftId, game: l.game,
  opponent: l.opponent, result: l.result, time: l.time, clearTime: l.clearTime, restarts: l.restarts,
  oppTime: l.oppTime, firstPick: l.firstPick, team: l.team.join(' | '),
})))));

fs.writeFileSync(path.join(outDir, 'agents.csv'), toCsv(agentStats.map(({ id, ...a }) => ({ ...a, id }))));

fs.writeFileSync(path.join(outDir, 'report.html'), renderHtml(playerStats, agentStats, matches.length, games.length));

console.log(`Матчей: ${matches.length}, игр: ${games.length}, игроков: ${playerStats.length}`);
console.log(`Готово: ${path.resolve(outDir)}/report.html, stats.json, players.csv, games.csv, agents.csv`);

// ---------- HTML ----------
function renderHtml(players, agents, matchCount, gameCount) {
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmtDate = d => esc(d.slice(0, 16).replace('T', ' '));
  const resCls = r => (r === 'W' ? 'win' : r === 'L' ? 'loss' : 'draw');

  const summaryRows = players.map(p => `<tr>
    <td><a href="#p-${esc(p.userId)}">${esc(p.name)}</a></td>
    <td>${p.matches}</td><td>${p.matchWins}-${p.matchLosses}${p.matchDraws ? `-${p.matchDraws}` : ''}</td><td>${p.matchWinrate}%</td>
    <td>${p.games}</td><td>${p.gameWinrate}%</td><td>${p.avgTime}</td><td>${p.bestTime}</td><td>${p.avgRestarts}</td>
    <td>${p.agents.slice(0, 3).map(a => esc(a.name)).join(', ')}</td></tr>`).join('');

  const playerSections = players.map(p => `
  <section class="player" id="p-${esc(p.userId)}">
    <h2>${esc(p.name)}${p.aliases.length > 1 ? ` <small>(${p.aliases.map(esc).join(', ')})</small>` : ''}</h2>
    <div class="tiles">
      <div><b>${p.matchWinrate}%</b><span>винрейт матчей (${p.matchWins}/${p.matches})</span></div>
      <div><b>${p.gameWinrate}%</b><span>винрейт игр (${p.gameWins}/${p.games})</span></div>
      <div><b>${p.avgTime}</b><span>среднее время, c</span></div>
      <div><b>${p.bestTime}</b><span>лучшее время, c</span></div>
      <div><b>${p.avgRestarts}</b><span>рестартов за игру</span></div>
      <div><b>${p.tournaments.length}</b><span>турниров</span></div>
    </div>
    <div class="cols">
      <div><h3>Агенты</h3><table><thead><tr><th>Агент</th><th>Игр</th><th>Пикрейт</th><th>Винрейт</th><th>Ср. M</th></tr></thead><tbody>
        ${p.agents.map(a => `<tr><td>${esc(a.name)}</td><td>${a.games}</td><td>${a.pickrate}%</td><td>${a.winrate}%</td><td>${a.avgMindscape}</td></tr>`).join('')}
      </tbody></table></div>
      <div><h3>Соперники</h3><table><thead><tr><th>Игрок</th><th>Матчи</th><th>Игры</th><th>Винрейт игр</th></tr></thead><tbody>
        ${p.opponents.map(o => `<tr><td><a href="#p-${esc(o.userId)}">${esc(o.name)}</a></td><td>${o.matchWins}/${o.matches}</td><td>${o.gameWins}/${o.games}</td><td>${o.gameWinrate}%</td></tr>`).join('')}
      </tbody></table>
      <h3>Движки</h3><table><thead><tr><th>Движок</th><th>Игр</th><th>Пикрейт</th><th>Винрейт</th></tr></thead><tbody>
        ${p.engines.slice(0, 10).map(e => `<tr><td>${esc(e.name)}</td><td>${e.games}</td><td>${e.pickrate}%</td><td>${e.winrate}%</td></tr>`).join('')}
      </tbody></table></div>
    </div>
    <details><summary>Все игры по порядку (${p.log.length})</summary>
      <table class="log"><thead><tr><th>Дата</th><th>Турнир</th><th>Игра</th><th>Соперник</th><th>Итог</th><th>Время</th><th>Рестарты</th><th>Состав</th></tr></thead><tbody>
      ${p.log.map(l => `<tr><td>${fmtDate(l.date)}</td><td>${esc(l.tournament)}</td><td title="${esc(l.draftId)}">${l.game}${l.firstPick ? ' ★' : ''}</td>
        <td>${esc(l.opponent)}</td><td class="${resCls(l.result)}">${l.result}</td><td>${l.time} : ${l.oppTime}</td><td>${l.restarts}</td>
        <td class="team">${l.team.map(esc).join('<br>')}</td></tr>`).join('')}
      </tbody></table>
    </details>
  </section>`).join('');

  const agentRows = agents.map(a => `<tr><td>${esc(a.name)}</td><td>${a.picks}</td><td>${a.pickrate}%</td><td>${a.winrate}%</td><td>${a.players}</td></tr>`).join('');

  return `<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Draft Stats</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e2e2dc;--accent:#2f6fde;--win:#1f8a4c;--loss:#c23b31;--draw:#8a6d1f}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecece8;--muted:#9b9b94;--card:#1e1e1c;--line:#33332f;--accent:#7aa5f0;--win:#5cc98a;--loss:#f07a70;--draw:#d8b75c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;padding:16px}
main{max-width:1200px;margin:0 auto}h1{margin:0 0 4px}h2{margin:0 0 12px}h2 small{color:var(--muted);font-weight:400}h3{margin:16px 0 8px;font-size:15px}
.sub{color:var(--muted);margin-bottom:20px}a{color:var(--accent);text-decoration:none}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px;overflow-x:auto}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px}td.team{white-space:normal;font-size:12px;color:var(--muted);min-width:260px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.tiles div{border:1px solid var(--line);border-radius:8px;padding:10px}.tiles b{display:block;font-size:20px}.tiles span{color:var(--muted);font-size:12px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
details{margin-top:16px}summary{cursor:pointer;font-weight:600}
.win{color:var(--win);font-weight:700}.loss{color:var(--loss);font-weight:700}.draw{color:var(--draw);font-weight:700}
</style></head><body><main>
<h1>Статистика игроков</h1>
<div class="sub">Матчей: ${matchCount} · игр: ${gameCount} · игроков: ${players.length}. Победа в игре — меньшее время с учётом штрафа за платные рестарты; матч — по сумме времени двух игр. ★ — первый пик.</div>
<section><h2>Общая таблица</h2><table><thead><tr><th>Игрок</th><th>Матчи</th><th>W-L</th><th>Винрейт</th><th>Игры</th><th>Винрейт игр</th><th>Ср. время</th><th>Лучшее</th><th>Рестарты/игра</th><th>Любимые агенты</th></tr></thead>
<tbody>${summaryRows}</tbody></table></section>
<section><h2>Агенты (все игроки)</h2><table><thead><tr><th>Агент</th><th>Пиков</th><th>Пикрейт</th><th>Винрейт</th><th>Игроков</th></tr></thead><tbody>${agentRows}</tbody></table></section>
${playerSections}
</main></body></html>`;
}
