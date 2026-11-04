import { useEffect, useState } from "react";
import { useLang } from "../i18n";
import type { LiveStream } from "../schedule/api";
import "./twitch-player.css";

// Twitch's embedded player for the streams on air, muted until the viewer turns the sound on; with several, buttons
// pick which. Twitch wants the page's host as "parent", known only in the browser, so it renders after mounting.
export function TwitchPlayer({ streams, className = "" }: { streams: LiveStream[]; className?: string }) {
  const { t } = useLang();
  const [host, setHost] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => setHost(window.location.hostname), []);
  const stream = streams.find((s) => s.channel === picked) ?? streams[0];
  if (!stream) return null;
  const src = host && `https://player.twitch.tv/?${new URLSearchParams({ channel: stream.channel, parent: host, muted: "true" })}`;
  return (
    <div className={`twitch-player ${className}`}>
      {streams.length > 1 && (
        <div className="twitch-player-pick" role="group" aria-label={t("Streams on air", "Трансляции в эфире")}>
          {streams.map((s) => (
            <button type="button" key={s.channel} aria-pressed={s.channel === stream.channel} onClick={() => setPicked(s.channel)}>{s.name}</button>
          ))}
        </div>
      )}
      <div className="twitch-player-frame">
        {src && <iframe key={stream.channel} src={src} title={`${stream.name} · Twitch`} allowFullScreen allow="autoplay; fullscreen" />}
      </div>
      <a className="twitch-player-link" href={`https://www.twitch.tv/${stream.channel}`} target="_blank" rel="noreferrer" title={stream.title ?? undefined}>
        {t("Open on Twitch", "Открыть на Twitch")} ↗
      </a>
    </div>
  );
}
