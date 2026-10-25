import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useLang } from "../i18n";
import { fetchEloHistory, type EloHistory, type EloPoint } from "./api";
import "./elo-chart.css";

const START = 1500; // everyone's rating before their first match (api/app/services/stats/elo.py)
const HEIGHT = 220;
const PAD = { top: 16, right: 16, bottom: 26, left: 44 };

// Round numbers for the y axis: a step of 25, 50, 100 or 200 giving about four lines.
function yTicks(lo: number, hi: number) {
  const step = [25, 50, 100, 200, 400].find((s) => (hi - lo) / s <= 5) ?? 400;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  return ticks;
}

// Month starts across the range, thinned to fit the width.
function xTicks(from: number, to: number, width: number) {
  const months: number[] = [];
  const d = new Date(from);
  d.setDate(1);
  d.setHours(0, 0, 0, 0);
  d.setMonth(d.getMonth() + 1);
  while (d.getTime() <= to) {
    months.push(d.getTime());
    d.setMonth(d.getMonth() + 1);
  }
  const every = Math.max(1, Math.ceil(months.length / Math.max(2, Math.floor(width / 90))));
  return months.filter((_, i) => i % every === 0);
}

// The player's Elo over time: one line, a dashed 1500 start, the peak marked; hover shows the match, a click opens it.
export function EloChart({ playerId }: { playerId: string }) {
  const { t, date, locale } = useLang();
  const navigate = useNavigate();
  const [data, setData] = useState<EloHistory | null | undefined>(undefined);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    fetchEloHistory(playerId, controller.signal).then(setData).catch(() => { if (!controller.signal.aborted) setData(null); });
    return () => controller.abort();
  }, [playerId]);

  useEffect(() => {
    if (!box.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, [data]);

  const points = data?.points ?? [];
  const geometry = useMemo(() => {
    if (!points.length || !width) return null;
    const times = points.map((p) => new Date(p.date).getTime());
    const from = times[0], to = Math.max(times[times.length - 1], from + 86400000);
    const values = points.map((p) => p.elo).concat(START);
    const lo = Math.floor((Math.min(...values) - 15) / 25) * 25, hi = Math.ceil((Math.max(...values) + 15) / 25) * 25;
    const plotW = width - PAD.left - PAD.right, plotH = HEIGHT - PAD.top - PAD.bottom;
    const x = (time: number) => PAD.left + ((time - from) / (to - from)) * plotW;
    const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * plotH;
    const xs = times.map(x);
    const path = points.map((p, i) => `${i ? "L" : "M"}${xs[i].toFixed(1)},${y(p.elo).toFixed(1)}`).join("");
    const peak = points.reduce((best, p, i) => (p.elo > points[best].elo ? i : best), 0);
    return { x, y, xs, path, peak, lo, hi, from, to, plotW, plotH };
  }, [points, width]);

  if (data === null) return null; // no rated matches: no chart
  const shown = hover != null ? points[hover] : null;

  function pick(clientX: number) {
    if (!geometry || !box.current) return;
    const px = clientX - box.current.getBoundingClientRect().left;
    let best = 0;
    geometry.xs.forEach((x, i) => { if (Math.abs(x - px) < Math.abs(geometry.xs[best] - px)) best = i; });
    setHover(best);
  }

  const result = (p: EloPoint) => p.result === 1 ? t("won", "победа") : p.result === 0 ? t("lost", "поражение") : t("draw", "ничья");
  return (
    <section className="player-box elo-chart-box">
      <h2 className="player-box-title">{t("Elo over time", "Эло за всё время")}</h2>
      <div className="elo-chart" ref={box}>
        {!data ? <p className="match-empty">…</p> : geometry && (
          <svg width={width} height={HEIGHT} role="img"
            aria-label={t(`Elo from ${START} to ${data.elo.rating} over ${points.length} matches`, `Эло от ${START} до ${data.elo.rating} за ${points.length} матчей`)}
            onMouseMove={(e) => pick(e.clientX)} onMouseLeave={() => setHover(null)}
            onTouchStart={(e) => pick(e.touches[0].clientX)} onTouchMove={(e) => pick(e.touches[0].clientX)}
            onClick={() => { const p = hover != null ? points[hover] : null; if (p?.match_id) navigate(`/match/${p.match_id}`); }}
            style={{ cursor: shown?.match_id ? "pointer" : "default" }}>
            {yTicks(geometry.lo, geometry.hi).map((v) => (
              <g key={v}>
                <line className="elo-grid" x1={PAD.left} x2={width - PAD.right} y1={geometry.y(v)} y2={geometry.y(v)} />
                <text className="elo-axis" x={PAD.left - 6} y={geometry.y(v)} textAnchor="end" dominantBaseline="middle">{v}</text>
              </g>
            ))}
            {xTicks(geometry.from, geometry.to, geometry.plotW).map((time) => (
              <text key={time} className="elo-axis" x={geometry.x(time)} y={HEIGHT - 8} textAnchor="middle">
                {new Date(time).toLocaleDateString(locale, { month: "short", year: "2-digit" })}
              </text>
            ))}
            <line className="elo-start" x1={PAD.left} x2={width - PAD.right} y1={geometry.y(START)} y2={geometry.y(START)} />
            <path className="elo-line" d={geometry.path} />
            <circle className="elo-peak" cx={geometry.xs[geometry.peak]} cy={geometry.y(points[geometry.peak].elo)} r={4} />
            <text className="elo-label" x={geometry.xs[geometry.peak]} y={geometry.y(points[geometry.peak].elo) - 9}
              textAnchor={geometry.xs[geometry.peak] > width - 80 ? "end" : "middle"}>{t("peak", "пик")} {points[geometry.peak].elo}</text>
            {shown && hover != null && (
              <g>
                <line className="elo-cross" x1={geometry.xs[hover]} x2={geometry.xs[hover]} y1={PAD.top} y2={HEIGHT - PAD.bottom} />
                <circle className="elo-dot" cx={geometry.xs[hover]} cy={geometry.y(shown.elo)} r={4.5} />
              </g>
            )}
          </svg>
        )}
        {shown && geometry && hover != null && (
          <div className="elo-tip" style={{ left: Math.min(Math.max(geometry.xs[hover], 90), width - 90), top: Math.max(geometry.y(shown.elo) - 12, 0) }}>
            <strong>{shown.elo}</strong>
            <span className={shown.change >= 0 ? "elo-up" : "elo-down"}> {shown.change >= 0 ? "+" : "−"}{Math.abs(shown.change).toFixed(1)}</span>
            <div>{result(shown)} · {shown.opponent.name}</div>
            <div className="elo-tip-meta">{shown.tournament} · {date(shown.date)}</div>
          </div>
        )}
      </div>
      {data && (
        <details className="elo-table">
          <summary className="player-label">{t("As a table", "Таблицей")}</summary>
          <table>
            <thead><tr><th>{t("Date", "Дата")}</th><th>{t("Opponent", "Соперник")}</th><th>{t("Result", "Итог")}</th><th>±</th><th>{t("Elo", "Эло")}</th></tr></thead>
            <tbody>
              {[...points].reverse().map((p, i) => (
                <tr key={i}>
                  <td className="gitv-date">{date(p.date)}</td><td>{p.opponent.name}</td><td>{result(p)}</td>
                  <td className={p.change >= 0 ? "elo-up" : "elo-down"}>{p.change >= 0 ? "+" : "−"}{Math.abs(p.change).toFixed(1)}</td><td>{p.elo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}
