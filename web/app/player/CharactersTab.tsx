import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useLang } from "../i18n";
import { fetchCharacterRoster, type CharacterRoster, type OwnedCharacter } from "./api";

type Sort = "picks" | "winrate" | "constellation" | "banned" | "name" | "changed";
const SORTS: { value: Sort; label: [string, string] }[] = [
  { value: "picks", label: ["Most picked", "Чаще пикает"] },
  { value: "winrate", label: ["Winrate", "Винрейт"] },
  { value: "constellation", label: ["Constellation", "Созвездие"] },
  { value: "banned", label: ["Banned against", "Банят против"] },
  { value: "changed", label: ["Latest constellation change", "Последнее изменение конст"] },
  { value: "name", label: ["Name", "Имя"] },
];

function lastChange(c: OwnedCharacter) {
  return c.history.length > 1 ? c.history[c.history.length - 1].date : "";
}

function sorted(rows: OwnedCharacter[], sort: Sort, name: (c: OwnedCharacter["character"]) => string) {
  const by: Record<Sort, (a: OwnedCharacter, b: OwnedCharacter) => number> = {
    picks: (a, b) => b.picks - a.picks || b.banned_against - a.banned_against,
    // Characters never played (no winrate) go last.
    winrate: (a, b) => (b.winrate ?? -1) - (a.winrate ?? -1) || b.picks - a.picks,
    constellation: (a, b) => b.constellation - a.constellation || (b.character.rarity ?? 0) - (a.character.rarity ?? 0),
    banned: (a, b) => b.banned_against - a.banned_against || b.picks - a.picks,
    changed: (a, b) => lastChange(b).localeCompare(lastChange(a)) || b.picks - a.picks,
    name: (a, b) => name(a.character).localeCompare(name(b.character)),
  };
  return [...rows].sort(by[sort]);
}

// The constellation's path: C0 → C1 → C3, each step with the date and tournament it first showed in.
function History({ c }: { c: OwnedCharacter }) {
  const { t, date } = useLang();
  if (c.history.length <= 1) {
    return <span className="player-label chars-history-none">{c.first_seen ? `${t("since", "с")} ${date(c.first_seen)}` : "—"}</span>;
  }
  return (
    <span className="chars-history">
      {c.history.map((h, i) => (
        <span key={i} className="chars-step" title={`${h.tournament.title} · ${date(h.date)}`}>
          {i > 0 && <span className="chars-arrow">→</span>}
          <b>C{h.constellation}</b>
          <small>{date(h.date)}</small>
        </span>
      ))}
    </span>
  );
}

// Shown while the character's name is hovered or focused: every game the player picked it in.
function PickedGames({ c }: { c: OwnedCharacter }) {
  const { t, date, name } = useLang();
  const letter = (r: string) => (r === "W" ? t("W", "В") : r === "L" ? t("L", "П") : r === "D" ? t("D", "Н") : "—");
  return (
    <div className="chars-games" role="tooltip">
      <div className="chars-games-head">
        <b>{name(c.character)}</b>
        <span className="player-label">{t(`picked in ${c.games.length} games`, `пикался в ${c.games.length} играх`)}</span>
      </div>
      <div className="chars-games-list">
        {c.games.map((g) => (
          <Link key={`${g.match_id}-${g.game_no}`} to={`/match/${g.match_id}`} className="chars-game">
            <span className={`chars-game-result ${g.result === "W" ? "win" : g.result === "L" ? "loss" : ""}`} title={g.technical ? t("Technical game", "Техническая игра") : undefined}>
              {letter(g.result)}{g.technical ? "*" : ""}
            </span>
            <span className="chars-game-main">
              <span className="player-ellipsis">{t("vs", "против")} <b>{g.opponent.name}</b></span>
              <small className="player-ellipsis">{g.tournament} · {t("game", "игра")} {g.game_no}</small>
            </span>
            <span className="chars-game-side">
              <span>{g.clear_time == null ? "—" : `${g.clear_time}s`}{g.constellation != null && <small> · C{g.constellation}</small>}</span>
              <small>{date(g.date)}</small>
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function CharactersTab({ playerId }: { playerId: string }) {
  const l = useLang();
  const { t, name, date, count } = l;
  const [tournament, setTournament] = useState("");
  const [data, setData] = useState<CharacterRoster | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("picks");
  const [playedOnly, setPlayedOnly] = useState(false);
  const [changedOnly, setChangedOnly] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetchCharacterRoster(playerId, tournament || undefined, controller.signal)
      .then(setData)
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the roster.", "Не удалось загрузить ростер.")); });
    return () => controller.abort();
  }, [playerId, tournament]);

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    const filtered = data.characters.filter((c) =>
      (!needle || c.character.name.toLowerCase().includes(needle) || (c.character.name_ru ?? "").toLowerCase().includes(needle))
      && (!playedOnly || c.picks > 0)
      && (!changedOnly || (tournament ? c.previous_constellation != null && c.previous_constellation !== c.constellation : c.history.length > 1)));
    return sorted(filtered, sort, name);
  }, [data, search, sort, playedOnly, changedOnly, tournament, name]);

  const pct = (v: number | null) => (v == null ? "—" : `${v}%`);
  const changedCount = data ? data.characters.filter((c) => (tournament ? c.previous_constellation != null && c.previous_constellation !== c.constellation : c.history.length > 1)).length : 0;

  return (
    <section className="player-box">
      <h2 className="player-box-title">{t("Characters", "Персонажи")}{data ? ` · ${data.characters.length}` : ""}</h2>
      <div className="chars-toolbar">
        <label className="chars-roster">
          <span className="player-label">{t("Roster", "Ростер")}</span>
          <select className="match-input" value={tournament} onChange={(e) => setTournament(e.target.value)} aria-label={t("Roster of", "Ростер на")}>
            <option value="">{t("All time: every character ever owned", "За всё время: все персонажи")}</option>
            {data?.tournaments.map((tr) => (
              <option key={tr.id} value={tr.id}>{tr.title} · {date(tr.date)}{tr.versions > 1 ? ` · ${t("changed mid-tournament", "менялся по ходу")}` : ""}</option>
            ))}
          </select>
        </label>
        <input className="match-input chars-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder={t("Character", "Персонаж")} aria-label={t("Find a character", "Найти персонажа")} />
        <select className="match-input" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label={t("Sort by", "Сортировка")}>
          {SORTS.map((s) => <option key={s.value} value={s.value}>{t(...s.label)}</option>)}
        </select>
        <button type="button" className={`player-control${playedOnly ? " active" : ""}`} aria-pressed={playedOnly} onClick={() => setPlayedOnly(!playedOnly)}>
          {t("Played only", "Только сыгранные")}
        </button>
        <button type="button" className={`player-control${changedOnly ? " active" : ""}`} aria-pressed={changedOnly} onClick={() => setChangedOnly(!changedOnly)}>
          {tournament ? t("Constellation up here", "Конста выросла") : t("Constellation changed", "Конста менялась")} · {changedCount}
        </button>
      </div>

      {error ? <p className="player-message">{error}</p>
        : !data ? <p className="player-message">{t("Loading roster…", "Загрузка ростера…")}</p>
        : data.characters.length === 0 ? <p className="player-message">{t("No roster data for this player.", "Нет данных о ростере игрока.")}</p>
        : <>
          <p className="player-note chars-note">
            {tournament
              ? t(`The roster in this tournament; stats from its ${count(data.games, ["game", "games"], ["игра", "игры", "игр"])}.`,
                  `Ростер на этом турнире; статистика по ${count(data.games, ["game", "games"], ["игре", "играм", "играм"])} турнира.`)
              : t(`Every character that was ever in the roster; stats from all ${count(data.games, ["game", "games"], ["игра", "игры", "игр"])}.`,
                  `Все персонажи, которые когда-либо были в ростере; статистика по всем ${count(data.games, ["game", "games"], ["игре", "играм", "играм"])}.`)}
          </p>
          <div className="chars-row chars-head player-label">
            <span /><span>{t("Character", "Персонаж")}</span><span>{t("Const.", "Конста")}</span>
            <span className="hide-sm">{t("Constellation history", "История созвездий")}</span>
            <span>{t("Picks", "Пики")}</span><span>{t("W–L · WR", "П–П · ВР")}</span>
            <span className="hide-xs">{t("Avg time", "Ср. время")}</span><span className="hide-xs">{t("Bans vs", "Баны")}</span>
          </div>
          {rows.map((c) => {
            const up = tournament && c.previous_constellation != null && c.constellation > c.previous_constellation;
            return (
              <div className={`chars-row${c.picks ? "" : " is-unplayed"}`} key={c.character.id}>
                {c.character.icon ? <img src={c.character.icon} alt="" width={30} height={30} loading="lazy" className={`chars-icon rarity-${c.character.rarity ?? 4}`} /> : <span className="chars-icon" />}
                <span className={`chars-name${c.games.length ? " has-games" : ""}`} tabIndex={c.games.length ? 0 : undefined}
                  aria-label={c.games.length ? t(`${name(c.character)}: games it was picked in`, `${name(c.character)}: игры с этим персонажем`) : undefined}>
                  {c.games.length > 0 && <PickedGames c={c} />}
                  <b className="player-ellipsis">{name(c.character)}</b>
                  <small className="player-label">
                    {c.level ? `Lv. ${c.level}` : ""}{!tournament && c.tournaments ? `${c.level ? " · " : ""}${count(c.tournaments, ["tournament", "tournaments"], ["турнир", "турнира", "турниров"])}` : ""}
                  </small>
                </span>
                <span className={`chars-cons c${c.constellation}`}>
                  C{c.constellation}
                  {up && <small className="chars-up" title={t(`Was C${c.previous_constellation} before this tournament`, `До этого турнира было C${c.previous_constellation}`)}>↑{c.constellation - c.previous_constellation!}</small>}
                </span>
                <span className="hide-sm"><History c={c} /></span>
                <span title={c.last_picked ? `${t("Last picked", "Последний пик")}: ${date(c.last_picked)}` : undefined}>
                  {c.picks}<small className="player-label"> · {pct(c.pick_rate)}</small>
                </span>
                <span>{c.wins + c.losses ? <>{c.wins}–{c.losses}<small className="player-label"> · {pct(c.winrate)}</small></> : "—"}</span>
                <span className="hide-xs">{c.avg_time == null ? "—" : `${c.avg_time}s`}</span>
                <span className="hide-xs">{c.banned_against || "—"}</span>
              </div>
            );
          })}
          {rows.length === 0 && <p className="player-message">{t("No characters match the filters.", "Нет персонажей под эти фильтры.")}</p>}
        </>}
    </section>
  );
}
