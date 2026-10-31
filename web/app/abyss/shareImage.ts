// A phase as a 1920×1080 picture to share (the "Download image" button): drawn on a canvas, no libraries.
// Version and dates, the moon blessing, Ley Line Disorder, floor HP, and the three chambers with each half's
// enemies (icon, element, count, HP). Icons are served by the API, so the canvas stays exportable.

import type { AbyssMonster, Chamber, PhaseDetail, Text } from "./api";

const W = 1920;
const H = 1080;
const PAD = 72;
const DISPLAY = '"Archivo", "IBM Plex Sans", system-ui, sans-serif';
const BODY = '"IBM Plex Sans", system-ui, sans-serif';
const C = {
  text: "#e2e8f0", soft: "#cbd5e1", muted: "#94a3b8", faint: "#64748b", border: "rgba(148, 163, 184, .18)",
  panel: "rgba(15, 23, 42, .72)", gold: "#f5c542", now: "#4ade80", next: "#93c5fd",
};
const ELEMENT: Record<string, string> = {
  Pyro: "#ef7a35", Hydro: "#4cc2f1", Cryo: "#9fd6e3", Electro: "#b38df2", Anemo: "#74c2a8", Geo: "#f2b723", Dendro: "#a5c83b",
};
const ELEMENT_FILE: Record<string, string> = {
  Pyro: "Fire", Hydro: "Water", Cryo: "Ice", Electro: "Elec", Anemo: "Wind", Geo: "Rock", Dendro: "Grass",
};

export type CardText = {
  ru: boolean;
  tx: (t: Text) => string; // a text in the site's language
  date: (iso: string) => string;
};

function load(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

function hp(value: number | null, ru: boolean) {
  if (value == null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2).replace(".", ru ? "," : ".")}${ru ? " млн" : "M"}`;
  return `${Math.round(value / 1000)}${ru ? " тыс." : "K"}`;
}

// Words into lines that fit the width; the last kept line ends with "…" when the text goes on.
function wrap(ctx: CanvasRenderingContext2D, text: string, width: number, maxLines: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width <= width || !line) line = next;
    else { lines.push(line); line = word; }
  }
  if (line) lines.push(line);
  if (lines.length <= maxLines) return lines;
  const kept = lines.slice(0, maxLines);
  let last = kept[maxLines - 1];
  while (last && ctx.measureText(`${last}…`).width > width) last = last.slice(0, -1);
  kept[maxLines - 1] = `${last.trimEnd()}…`;
  return kept;
}

function fit(ctx: CanvasRenderingContext2D, text: string, width: number) {
  if (ctx.measureText(text).width <= width) return text;
  let s = text;
  while (s && ctx.measureText(`${s}…`).width > width) s = s.slice(0, -1);
  return `${s.trimEnd()}…`;
}

function panel(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) {
  ctx.fillStyle = C.panel;
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 14);
  ctx.fill();
  ctx.stroke();
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color = C.muted) {
  ctx.font = `600 20px ${BODY}`;
  ctx.fillStyle = color;
  ctx.letterSpacing = "2px";
  ctx.fillText(text.toUpperCase(), x, y);
  ctx.letterSpacing = "0px";
}

// A half's enemies, the same one merged across waves, strongest first.
function enemies(chamber: Chamber): AbyssMonster[] {
  const byId = new Map<number, AbyssMonster>();
  for (const m of chamber.waves.flatMap((w) => w.monsters)) {
    const seen = byId.get(m.id);
    byId.set(m.id, seen ? { ...seen, count: seen.count + m.count } : { ...m });
  }
  return [...byId.values()].sort((a, b) => b.hp - a.hp);
}

function background(ctx: CanvasRenderingContext2D) {
  const base = ctx.createLinearGradient(0, 0, W, H);
  base.addColorStop(0, "#070c18");
  base.addColorStop(1, "#111a33");
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, W, H);
  const glow = (x: number, y: number, r: number, color: string) => {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, color);
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  };
  glow(1650, 120, 760, "rgba(59, 130, 246, .22)");
  glow(160, 1040, 640, "rgba(245, 197, 66, .08)");
  // The abyss: thin rings around the top right
  ctx.lineWidth = 1.5;
  for (let i = 0; i < 9; i++) {
    ctx.strokeStyle = `rgba(147, 197, 253, ${0.13 - i * 0.012})`;
    ctx.beginPath();
    ctx.arc(1700, 150, 90 + i * 70, 0, Math.PI * 2);
    ctx.stroke();
  }
}

export async function abyssCard(phase: PhaseDetail, l: CardText): Promise<Blob> {
  const { ru, tx, date } = l;
  const t = (en: string, rus: string) => (ru ? rus : en);
  await Promise.all([
    document.fonts.load(`800 104px "Archivo"`), document.fonts.load(`600 20px "IBM Plex Sans"`),
    document.fonts.load(`400 22px "IBM Plex Sans"`), document.fonts.load(`700 22px "IBM Plex Sans"`),
  ]).catch(() => {});
  const halves = [1, 2, 3].map((n) => phase.chambers.filter((c) => c.index === n).sort((a, b) => a.half - b.half));
  const icons = new Map<string, HTMLImageElement | null>();
  const wanted = new Set<string>(["/Logo.jpeg"]);
  for (const c of phase.chambers) for (const m of enemies(c).slice(0, 5)) if (m.icon) wanted.add(m.icon);
  for (const e of Object.values(ELEMENT_FILE)) wanted.add(`/api/v1/abyss-assets/elements/${e}.png`);
  await Promise.all([...wanted].map(async (src) => icons.set(src, await load(src))));

  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d")!;
  ctx.textBaseline = "alphabetic";
  background(ctx);

  // Header: the site, then the phase
  const logo = icons.get("/Logo.jpeg");
  if (logo) {
    ctx.save();
    ctx.beginPath();
    ctx.roundRect(PAD, 56, 64, 64, 12);
    ctx.clip();
    ctx.drawImage(logo, PAD, 56, 64, 64);
    ctx.restore();
  }
  ctx.font = `800 40px ${DISPLAY}`;
  ctx.fillStyle = C.text;
  ctx.fillText("GITV", PAD + 84, 102);
  ctx.textAlign = "right";
  label(ctx, t("Spiral Abyss · Floor 12", "Витая Бездна · 12 этаж"), W - PAD, 98);
  ctx.textAlign = "left";

  ctx.font = `800 112px ${DISPLAY}`;
  ctx.fillStyle = C.text;
  const title = `${t("Version", "Версия")} ${phase.version}`;
  ctx.fillText(title, PAD - 4, 262);
  const titleEnd = PAD + ctx.measureText(title).width + 28;
  const tag = phase.current ? [t("Now", "Сейчас"), C.now] : phase.upcoming ? [t("Next", "Следующая"), C.next] : null;
  if (tag) {
    ctx.font = `700 22px ${BODY}`;
    ctx.letterSpacing = "2px";
    const tw = ctx.measureText(tag[0].toUpperCase()).width + 32;
    ctx.strokeStyle = tag[1];
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(titleEnd, 206, tw, 44, 8);
    ctx.stroke();
    ctx.fillStyle = tag[1];
    ctx.fillText(tag[0].toUpperCase(), titleEnd + 16, 236);
    ctx.letterSpacing = "0px";
  }
  ctx.font = `400 32px ${BODY}`;
  ctx.fillStyle = C.muted;
  ctx.fillText(`${date(phase.starts_on)} – ${date(phase.ends_on)}`, PAD, 318);

  // HP at the top right
  const stats: [string, string][] = [
    [t("Floor 12 HP", "HP 12 этажа"), hp(phase.total_hp, ru)],
    [t("Enemy HP", "HP врагов"), phase.hp_ratio != null ? `×${String(phase.hp_ratio).replace(".", ru ? "," : ".")}` : "—"],
  ];
  if (phase.matches > 0) stats.push([t("Tournament matches", "Матчей турниров"), String(phase.matches)]);
  let sx = W - PAD;
  for (const [name, value] of [...stats].reverse()) {
    ctx.font = `800 64px ${DISPLAY}`;
    const vw = Math.max(ctx.measureText(value).width, 170);
    sx -= vw;
    label(ctx, name, sx, 214);
    ctx.font = `800 64px ${DISPLAY}`;
    ctx.fillStyle = C.text;
    ctx.fillText(value, sx, 286);
    sx -= 56;
  }

  // The rules: moon blessing and Ley Line Disorder
  const ruleY = 364;
  const ruleH = 236;
  const ruleW = (W - PAD * 2 - 24) / 2;
  panel(ctx, PAD, ruleY, ruleW, ruleH);
  label(ctx, t("Moon blessing", "Благословение луны"), PAD + 28, ruleY + 44);
  const blessing = phase.blessing_list[0];
  let by = ruleY + 44;
  if (blessing?.name) {
    ctx.font = `700 30px ${DISPLAY}`;
    ctx.fillStyle = C.gold;
    ctx.fillText(fit(ctx, blessing.name, ruleW - 56), PAD + 28, by + 44);
    by += 44;
  }
  ctx.font = `400 22px ${BODY}`;
  ctx.fillStyle = C.soft;
  const blessingLines = blessing ? wrap(ctx, tx(blessing.desc), ruleW - 56, blessing.name ? 3 : 4) : [];
  blessingLines.forEach((line, i) => ctx.fillText(line, PAD + 28, by + 38 + i * 30));

  const dx = PAD + ruleW + 24;
  panel(ctx, dx, ruleY, ruleW, ruleH);
  label(ctx, t("Ley Line Disorder", "Нарушение лей-линий"), dx + 28, ruleY + 44);
  let dy = ruleY + 88;
  for (const d of phase.disorder.slice(0, 3)) {
    const raw = tx(d);
    const half = raw.match(/^P([12])\s+(.*)$/);
    let x = dx + 28;
    if (half) {
      ctx.font = `700 22px ${BODY}`;
      ctx.fillStyle = C.next;
      const chip = t(`Half ${half[1]}`, `${half[1]}-я половина`);
      ctx.fillText(chip, x, dy);
      x += ctx.measureText(chip).width + 14;
    }
    ctx.font = `400 22px ${BODY}`;
    ctx.fillStyle = C.soft;
    const lines = wrap(ctx, half ? half[2] : raw, ruleW - 56 - (x - dx - 28), 2);
    lines.forEach((line, i) => ctx.fillText(line, x, dy + i * 31));
    dy += lines.length * 31 + 16;
  }

  // The chambers, each with its two halves stacked
  const roomY = 624;
  const roomH = 392;
  const roomW = (W - PAD * 2 - 48) / 3;
  halves.forEach((rows, i) => {
    const x = PAD + i * (roomW + 24);
    panel(ctx, x, roomY, roomW, roomH);
    ctx.font = `800 40px ${DISPLAY}`;
    ctx.fillStyle = C.text;
    ctx.fillText(`12-${i + 1}`, x + 28, roomY + 58);
    ctx.textAlign = "right";
    ctx.font = `600 22px ${BODY}`;
    ctx.fillStyle = C.muted;
    const level = rows[0]?.level != null ? `${t("Lv.", "Ур.")} ${rows[0].level} · ` : "";
    ctx.fillText(`${level}HP ${hp(rows.reduce((s, c) => s + c.hp, 0), ru)}`, x + roomW - 28, roomY + 56);
    ctx.textAlign = "left";
    rows.forEach((c, j) => {
      const y = roomY + 88 + j * 152;
      if (j > 0) {
        ctx.strokeStyle = C.border;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x + 28, y - 12);
        ctx.lineTo(x + roomW - 28, y - 12);
        ctx.stroke();
      }
      label(ctx, `${t(`Half ${c.half}`, `${c.half}-я половина`)} · HP ${hp(c.hp, ru)}`, x + 28, y + 16, C.faint);
      const list = enemies(c);
      const shown = list.slice(0, 4);
      const S = 84; // icon
      const step = S + 26;
      shown.forEach((m, k) => {
        const ix = x + 28 + k * step;
        const iy = y + 30;
        const r = S / 2;
        const ring = (m.element && ELEMENT[m.element]) || "#475569";
        ctx.fillStyle = "rgba(30, 41, 59, .9)";
        ctx.beginPath();
        ctx.arc(ix + r, iy + r, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = ring;
        ctx.lineWidth = 3;
        ctx.stroke();
        const icon = m.icon ? icons.get(m.icon) : null;
        if (icon) {
          ctx.save();
          ctx.beginPath();
          ctx.arc(ix + r, iy + r, r - 3, 0, Math.PI * 2);
          ctx.clip();
          ctx.drawImage(icon, ix + 3, iy + 3, S - 6, S - 6);
          ctx.restore();
        }
        const el = m.element && ELEMENT_FILE[m.element] ? icons.get(`/api/v1/abyss-assets/elements/${ELEMENT_FILE[m.element]}.png`) : null;
        if (el) ctx.drawImage(el, ix + S - 26, iy + S - 26, 28, 28);
        if (m.count > 1) {
          ctx.font = `700 18px ${BODY}`;
          const cw = ctx.measureText(`×${m.count}`).width + 12;
          ctx.fillStyle = "#0b1220";
          ctx.beginPath();
          ctx.roundRect(ix - 4, iy - 4, cw, 24, 6);
          ctx.fill();
          ctx.fillStyle = C.text;
          ctx.fillText(`×${m.count}`, ix + 2, iy + 14);
        }
        ctx.font = `600 18px ${BODY}`;
        ctx.fillStyle = C.soft;
        ctx.textAlign = "center";
        ctx.fillText(hp(m.hp, ru), ix + r, iy + S + 22);
        ctx.textAlign = "left";
      });
      let after = x + 28 + shown.length * step;
      if (list.length > shown.length) {
        ctx.font = `600 22px ${BODY}`;
        ctx.fillStyle = C.muted;
        ctx.fillText(`+${list.length - shown.length}`, after, y + 80);
        after += 44;
      }
      // The strongest enemy by name, when there's room beside the icons
      const room = x + roomW - 28 - after;
      if (shown[0] && room >= 150) {
        ctx.font = `700 21px ${BODY}`;
        ctx.fillStyle = C.text;
        const lines = wrap(ctx, shown[0].name, room, 3);
        const top = y + 30 + 84 / 2 - ((lines.length - 1) * 26) / 2 + 7;
        lines.forEach((line, i) => ctx.fillText(line, after, top + i * 26));
      }
    });
  });

  // Footer
  ctx.font = `400 20px ${BODY}`;
  ctx.fillStyle = C.faint;
  ctx.fillText(t("Abyss data: alioth.wiki · Enemy and element icons © HoYoverse", "Данные Бездны: alioth.wiki · Иконки врагов и стихий © HoYoverse"), PAD, H - 34);
  ctx.textAlign = "right";
  ctx.fillText(`${t("Spiral Abyss", "Витая Бездна")} ${phase.version} · GITV`, W - PAD, H - 34);
  ctx.textAlign = "left";

  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("canvas"))), "image/png"));
}
