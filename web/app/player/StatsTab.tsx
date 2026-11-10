import type { ReactNode } from "react";
import { Link } from "react-router";
import { useLang } from "../i18n";
import { EloBadge } from "../components/EloBadge";
import { Nick } from "../components/PlayerNick";
import { EloChart } from "./EloChart";
import type { CharacterRate, Finish, PlayerDetail, Split } from "./api";
import { GAMES, PLACE_LABELS, StatBox, StatRow, StatRows, resultLetter, seconds, type L } from "./playerParts";

function characterRate(l: L, item: CharacterRate | null) {
  return item ? `${l.name(item.character)} · ${item.winrate}% · ${l.count(item.games, ...GAMES)}` : "—";
}

// W / L in English, В (выигрыш) / П (поражение) in Russian.
function wl(l: L, wins: number, losses: number) {
  return l.t(`${wins}W / ${losses}L`, `${wins}В / ${losses}П`);
}

function split(l: L, s: Split) {
  return s.winrate == null ? "—" : `${s.winrate}% · ${wl(l, s.wins, s.losses)}`;
}

// Top-4 places, newest first: gold, silver, bronze, grey.
function Placements({ finishes }: { finishes: Finish[] }) {
  const l = useLang();
  return (
    <StatBox title={l.t("Placements", "Призовые места")}>
      {finishes.length ? (
        <div className="player-places">
          {finishes.map((f) => (
            <Link className="player-place" to={`/tournament/${f.tournament.id}`} key={f.tournament.id}
              title={`${l.t(...PLACE_LABELS[f.place - 1])} ${l.t("place", "место")} · ${l.date(f.date)}`}>
              <span className={`player-place-badge place-${f.place}`}>{f.place}</span>
              <span className="player-ellipsis">{f.tournament.title}</span>
            </Link>
          ))}
        </div>
      ) : <div className="player-box-body player-label">{l.t("No top-4 places yet.", "Мест в топ-4 пока нет.")}</div>}
    </StatBox>
  );
}

// Who the player met most: their record against each, and a link to compare the two.
function FrequentOpponents({ player }: { player: PlayerDetail }) {
  const l = useLang();
  const { t } = l;
  if (!player.frequent_opponents.length) return null;
  return (
    <StatBox title={t("Most frequent opponents", "Частые соперники")}>
      <div className="player-box-body">
        {player.frequent_opponents.map((o) => (
          <div className="player-opponent" key={o.player.id} tabIndex={0}
            aria-label={t(`Matches against ${o.player.name}`, `Матчи против ${o.player.name}`)}>
            <div className="player-opponent-pop" role="tooltip">
              <div className="player-opponent-pop-head">
                <b>{t("vs", "против")} {o.player.name}</b>
                <span className="player-label">{o.wins}–{o.losses}{o.matches > o.wins + o.losses ? ` · ${t("other", "прочие")} ${o.matches - o.wins - o.losses}` : ""}</span>
              </div>
              <div className="player-opponent-pop-list">
                {o.meetings.map((m) => (
                  <Link key={m.match_id} to={`/match/${m.match_id}`} className="player-opponent-meeting">
                    <span className={`player-opponent-res ${m.result === "W" ? "win" : m.result === "L" ? "loss" : ""}`}>{resultLetter(l, m.result)}</span>
                    <span className="player-opponent-meeting-main">
                      <b>{m.games_won}–{m.games_lost}</b>
                      <small className="player-ellipsis">{m.tournament}</small>
                    </span>
                    <span className="player-opponent-meeting-side">
                      {m.source === "challonge" && <span className="match-tag" title={t("Result from the Challonge bracket", "Результат из сетки Challonge")}>Ch</span>}
                      {m.source === "technical" && <span className="match-tag warn">{t("Tech", "Тех.")}</span>}
                      <small>{l.date(m.date)}</small>
                    </span>
                  </Link>
                ))}
              </div>
            </div>
            <div className="player-opponent-main">
              <Link className="player-match-link player-ellipsis player-opponent-name" to={`/player/${o.player.id}`}><Nick id={o.player.id} name={o.player.name} /></Link>
              <span className="player-label" title={`${t("Last met", "Последняя встреча")}: ${l.date(o.last_met)}`}>{l.count(o.matches, ["match", "matches"], ["матч", "матча", "матчей"])}</span>
            </div>
            <div className="player-opponent-record">
              <span><b className="player-opponent-w">{o.wins}</b> – <b className="player-opponent-l">{o.losses}</b></span>
              <span className="player-label">{o.winrate == null ? "—" : `${o.winrate}%`}</span>
            </div>
            <Link className="player-control player-opponent-vs" to={`/player/${player.id}/compare/${o.player.id}`}
              title={t(`Compare with ${o.player.name}`, `Сравнить с ${o.player.name}`)}>VS</Link>
          </div>
        ))}
      </div>
    </StatBox>
  );
}

export function StatsTab({ player }: { player: PlayerDetail }) {
  const l = useLang();
  const { t } = l;
  const times = player.times;
  return (
    <>
    <EloChart playerId={player.id} />
    <div className="player-columns">
      <aside className="player-column">
        <StatBox title={t("Streaks", "Серии")}>
          <StatRows rows={[[t("Highest winstreak", "Лучшая серия побед"), player.highest_winstreak], [t("Current winstreak", "Текущая серия побед"), player.current_winstreak]]} />
        </StatBox>
        <StatBox title={t("Last 10 games", "Последние 10 игр")}>
          {player.last_games.length
            ? (
              <div className="player-games player-games-line">
                {player.last_games.map((game, index) => (
                  <Link className={`player-game ${game.result === "W" ? "win" : game.result === "L" ? "loss" : ""}`} to={`/match/${game.match_id}`} key={index}
                    title={`${l.date(game.date)} · ${t("game", "игра")} ${game.game_no}`}
                    aria-label={`${game.result === "W" ? t("Win", "Победа") : game.result === "L" ? t("Loss", "Поражение") : t("Draw", "Ничья")}, ${t("game", "игра")} ${game.game_no}, ${t("open match", "открыть матч")}`}>
                    {resultLetter(l, game.result)}
                  </Link>
                ))}
              </div>
            )
            : <div className="player-box-body player-label">{t("No decided games yet.", "Сыгранных игр с результатом пока нет.")}</div>}
        </StatBox>
        <Placements finishes={player.finishes} />
      </aside>
      <div className="player-column">
        <StatBox title={t("Characters", "Персонажи")}>
          <StatRows rows={[
            [t("Highest winrate character", "Лучший винрейт"), characterRate(l, player.highest_winrate_character)],
            [t("Lowest winrate character", "Худший винрейт"), characterRate(l, player.lowest_winrate_character)],
          ]} />
        </StatBox>
        <StatBox title={t("Results", "Результаты")}>
          <StatRows rows={[
            ...(player.elo ? [[t("Elo", "Эло"), (
              <>
                <EloBadge rating={player.elo.rating} rank={player.elo.rank} tier={player.elo.tier} active={player.elo.active} />
                {` · ${player.elo.active ? `#${player.elo.rank}` : t("inactive", "неактивен")} · ${t("peak", "пик")} `}
                <EloBadge rating={player.elo.peak} active={player.elo.active} />
              </>
            )] as [string, ReactNode]] : []),
            [t("Matches", "Матчи"), `${player.matches} · ${player.match_winrate ?? "—"}% ${t("won", "побед")}`],
            [t("Winrate", "Винрейт"), player.winrate == null ? "—" : `${player.winrate}% · ${wl(l, player.wins, player.losses)}`],
            [t("First pick winrate", "Винрейт на первом пике"), split(l, player.first_pick)],
            [t("Second pick winrate", "Винрейт на втором пике"), split(l, player.second_pick)],
            [t("Technical lose rate", "Доля тех. поражений"), `${player.tech_loss_rate ?? 0}% · ${player.tech_losses} ${t("of", "из")} ${l.count(player.games, ...GAMES)}`],
          ]} />
        </StatBox>
      </div>
      <aside className="player-column">
        <StatBox title={t("Times", "Время")}>
          <div className="player-box-body">
            <StatRow label={t("Average time", "Среднее время")} value={seconds(l, times.average)} />
            <StatRow label={t("Average win time", "Среднее в победах")} value={seconds(l, times.average_win)} />
            <StatRow label={t("Average loss time", "Среднее в поражениях")} value={seconds(l, times.average_loss)} />
            <div className="player-row-gap" />
            <StatRow label={t("Average first pick time", "Среднее на первом пике")} value={seconds(l, times.average_first_pick)} />
            <StatRow label={t("Average second pick time", "Среднее на втором пике")} value={seconds(l, times.average_second_pick)} />
          </div>
        </StatBox>
        <p className="player-note player-label">
          {/* Russian: "по 1 игре / по 3 играм / по 61 игре" (dative), so the number and noun always agree. */}
          {t(`Times come from ${l.count(times.counted_games, ...GAMES)}; technical games are left out.`,
             `Время посчитано по ${l.count(times.counted_games, ["game", "games"], ["игре", "играм", "играм"])}; технические игры не учитываются.`)}
        </p>
        <FrequentOpponents player={player} />
      </aside>
    </div>
    </>
  );
}
