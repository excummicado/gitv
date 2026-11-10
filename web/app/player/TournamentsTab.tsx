import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useLang } from "../i18n";
import { fetchRosters, type PlayedTournament, type PlayerDetail, type RosterVersion } from "./api";
import { GAMES, PLACE_LABELS, StatBox } from "./playerParts";

// A yes/no choice kept in the browser (a roster view preference); false when storage is unavailable.
function useStoredFlag(key: string): [boolean, () => void] {
  const [on, setOn] = useState(() => {
    try { return localStorage.getItem(key) === "1"; } catch { return false; }
  });
  function toggle() {
    const next = !on;
    setOn(next);
    try { localStorage.setItem(key, next ? "1" : ""); } catch { /* storage unavailable: just this view */ }
  }
  return [on, toggle];
}

function FreeToggle({ hidden, count, onToggle }: { hidden: boolean; count: number; onToggle: () => void }) {
  const { t } = useLang();
  return (
    <button type="button" className={`player-control${hidden ? " active" : ""}`} aria-pressed={hidden} onClick={onToggle}>
      {hidden ? t(`Show 0-cost (${count})`, `Показать с костом 0 (${count})`) : t(`Hide 0-cost (${count})`, `Скрыть с костом 0 (${count})`)}
    </button>
  );
}

// A tournament's roster under its row: characters strongest first, then weapons; a version switch when it
// changed mid-tournament.
function RosterPanel({ playerId, tournamentId }: { playerId: string; tournamentId: string }) {
  const l = useLang();
  const { t } = l;
  const [versions, setVersions] = useState<RosterVersion[] | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState(0);
  // Characters and weapons that cost 0 in the tournament's system can be hidden, each on its own switch;
  // the choices stick across rosters.
  const [hideFree, toggleFree] = useStoredFlag("gitv-roster-hide-free");
  const [hideFreeWeapons, toggleFreeWeapons] = useStoredFlag("gitv-roster-hide-free-weapons");

  useEffect(() => {
    const controller = new AbortController();
    fetchRosters(playerId, tournamentId, controller.signal)
      .then((list) => { setVersions(list); setPicked(list.length - 1); })
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("Couldn't load the roster.", "Не удалось загрузить ростер.")); });
    return () => controller.abort();
  }, [playerId, tournamentId]);

  if (error) return <div className="roster-panel player-label">{error}</div>;
  if (!versions) return <div className="roster-panel player-label">{t("Loading roster…", "Загрузка ростера…")}</div>;
  const v = versions[picked];
  const free = v.characters.filter((c) => c.cost === 0).length;
  const shown = hideFree ? v.characters.filter((c) => c.cost !== 0) : v.characters;
  const freeWeapons = v.weapons.filter((w) => w.cost === 0).reduce((n, w) => n + w.count, 0);
  const shownWeapons = hideFreeWeapons ? v.weapons.filter((w) => w.cost !== 0) : v.weapons;
  const allWeapons = v.weapons.reduce((n, w) => n + w.count, 0);
  const weaponCount = shownWeapons.reduce((n, w) => n + w.count, 0);
  return (
    <div className="roster-panel">
      {versions.length > 1 && (
        <div className="roster-versions" role="group" aria-label={t("Roster version", "Версия ростера")}>
          <span className="player-label">{t("Changed during the tournament:", "Менялся по ходу турнира:")}</span>
          {versions.map((item, i) => (
            <button type="button" key={item.version} className={`player-control${i === picked ? " active" : ""}`} aria-pressed={i === picked} onClick={() => setPicked(i)}>
              {t(`Version ${item.version}`, `Версия ${item.version}`)} · {l.count(item.games, ...GAMES)}
            </button>
          ))}
        </div>
      )}
      <div className="roster-heading roster-heading--row">
        <span className="player-label">{t("Characters by cost", "Персонажи по косту")} · {shown.length === v.characters.length ? v.characters.length : `${shown.length} ${t("of", "из")} ${v.characters.length}`}</span>
        {free > 0 && <FreeToggle hidden={hideFree} count={free} onToggle={toggleFree} />}
      </div>
      <div className="roster-grid">
        {shown.map((c) => (
          <span className="roster-item" key={c.character.id} title={`${l.name(c.character)} · C${c.constellation}${c.level ? ` · Lv ${c.level}` : ""}${c.cost != null ? ` · ${t("cost", "кост")} ${c.cost}` : ""}`}>
            <span className="match-member-art">
              {c.character.icon ? <img className={`match-portrait rarity-${c.character.rarity ?? 4}`} src={c.character.icon} alt="" width={40} height={40} loading="lazy" /> : <span className="match-portrait" />}
              <span className="match-badge">C{c.constellation}</span>
            </span>
            <span className="roster-name">{l.name(c.character)}</span>
            <span className="roster-cost">{c.cost ?? "—"}</span>
          </span>
        ))}
      </div>
      <div className="roster-heading roster-heading--row">
        <span className="player-label">{t("Weapons by cost", "Оружие по косту")} · {weaponCount === allWeapons ? allWeapons : `${weaponCount} ${t("of", "из")} ${allWeapons}`}</span>
        {freeWeapons > 0 && <FreeToggle hidden={hideFreeWeapons} count={freeWeapons} onToggle={toggleFreeWeapons} />}
      </div>
      <div className="roster-grid roster-grid--weapons">
        {shownWeapons.map((w) => (
          <span className="roster-item" key={`${w.weapon.id}-${w.refinement}-${w.level}`} title={`${l.name(w.weapon)} · R${w.refinement ?? "?"}${w.count > 1 ? ` × ${w.count}` : ""}${w.cost != null ? ` · ${t("cost", "кост")} ${w.cost}` : ""}`}>
            <span className="match-member-art">
              {w.weapon.icon ? <img className={`match-portrait rarity-${w.weapon.rarity ?? 4}`} src={w.weapon.icon} alt="" width={34} height={34} loading="lazy" /> : <span className="match-portrait" />}
              <span className="match-badge">R{w.refinement ?? "?"}{w.count > 1 ? `×${w.count}` : ""}</span>
            </span>
            <span className="roster-cost">{w.cost ?? "—"}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// Brackets show the place (a medal for the top four, a tier like 5-8 below); group stages show the match score.
function PlaceOrScore({ item }: { item: PlayedTournament }) {
  const { t } = useLang();
  if (item.kind === "bracket" && item.place_range) {
    const [low, high] = item.place_range;
    const estimate = item.place_source === "estimate";
    const title = estimate
      ? t("Estimated from matches won: the tournament has no Challonge bracket.", "Оценка по выигранным матчам: у турнира нет сетки на Challonge.")
      : t("From the tournament's Challonge bracket.", "Из сетки турнира на Challonge.");
    if (low === high && low <= 4) {
      return <span className="player-tourney-place" title={title}><span className={`player-place-badge place-${low}`}>{low}</span>{t(...PLACE_LABELS[low - 1])} {t("place", "место")}</span>;
    }
    return <span title={title}>{estimate && "≈ "}{low === high ? low : `${low}–${high}`} {t("place", "место")}</span>;
  }
  return <span>{item.wins} – {item.losses}</span>;
}

// Third tab: every tournament the player played, the place (or group score), qualifiers passed or not, roster.
export function TournamentList({ player, playerId }: { player: PlayerDetail; playerId: string }) {
  const l = useLang();
  const { t } = l;
  const [open, setOpen] = useState<string | null>(null);
  const QUAL: Record<string, [string, string]> = { passed: ["Qualified", "Прошёл"], failed: ["Eliminated", "Не прошёл"], pending: ["Pending", "Ожидается"] };
  return (
    <StatBox title={`${t("Tournaments", "Турниры")} · ${player.tournament_list.length}`}>
      <div className="player-tourney player-match-head">
        <span>{t("Date", "Дата")}</span><span>{t("Tournament", "Турнир")}</span><span>{t("Place / score", "Место / счёт")}</span>
        <span>{t("Qualifiers", "Квалы")}</span><span />
      </div>
      {player.tournament_list.map((item) => (
        <div key={item.id}>
          <div className="player-tourney">
            <span className="gitv-date">{l.date(item.date)}</span>
            <Link className="player-ellipsis player-match-link" to={`/tournament/${item.id}`}>{item.title}</Link>
            <PlaceOrScore item={item} />
            <span>{item.qualification ? <span className={`player-qual ${item.qualification}`}>{t(...QUAL[item.qualification])}</span> : null}</span>
            <span className="player-tourney-roster">
              {item.rosters > 0 && (
                <button type="button" className={`player-control${open === item.id ? " active" : ""}`} aria-expanded={open === item.id}
                  onClick={() => setOpen(open === item.id ? null : item.id)}>
                  {t("Roster", "Ростер")}{item.rosters > 1 ? ` · ${item.rosters}` : ""}
                </button>
              )}
            </span>
          </div>
          {open === item.id && <RosterPanel playerId={playerId} tournamentId={item.id} />}
        </div>
      ))}
    </StatBox>
  );
}
