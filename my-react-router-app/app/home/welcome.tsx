import type { ReactNode } from "react";
import "./gitv-preview.css";

import { Link } from "react-router";

const rankings = [1, 2, 3, 4, 5];
const headlines = [1, 2, 3, 4, 5, 6];
const matches = [1, 2, 3, 4, 5];

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`gitv-card ${className}`}>{children}</section>;
}

function Rows({ count, children }: { count: number; children: (index: number) => ReactNode }) {
  return <>{Array.from({ length: count }, (_, index) => children(index))}</>;
}

function GitvPreview() {
  return (
    <div className="gitv-frame">
      <nav className="gitv-nav" aria-label="Preview navigation">
        <div className="gitv-nav-content">
          <span>Matches</span><span>Players</span><span>Tournaments</span><span>Abyss</span>
          <span className="gitv-search">Search...</span><Link to="/login"><span>Sign in</span></Link><span>Settings</span>
        </div>
      </nav>
      <div className="gitv-content">
        <header className="gitv-brand"><Link to="/"><img src="/Logo.png" alt="GITV Logo" className="gitv-mark" /><span>GITV</span></Link></header>
        <div className="gitv-columns">
          <aside>
            <Card><div className="gitv-image gitv-promo">Promo image</div></Card>
            <Card><div className="gitv-card-title">Active Players</div>
              <Rows count={rankings.length}>{(i) => <div className="gitv-row" key={i}><small>{i + 1}.</small><i className="gitv-square" />Name</div>}</Rows>
              <div className="gitv-foot">Link text<br />Updated: 00 Mon</div>
            </Card>
            <Card><div className="gitv-card-title">Upcoming Tournaments</div><div className="gitv-row"><i className="gitv-square" />Event name <b className="gitv-badge push">Live</b></div><div className="gitv-row"><i className="gitv-square" />Event name <small className="push">0 days</small></div></Card>
          </aside>
          <main>
            <div className="gitv-image gitv-banner">Event banner <b className="gitv-badge live">Live</b></div>
            <div className="gitv-tabs"><span>Overview</span><span>Matches</span><span>Results</span><span>Stats</span></div>
            <Card><div className="gitv-image gitv-feature">Featured image</div></Card>
            <div className="gitv-section-label">Today's News</div>
            <Card><Rows count={headlines.length}>{(i) => <div className="gitv-row gitv-headline" key={i}><i className="gitv-line" /><span>Headline text</span><small className="push">00 min ago<br />00 comments</small></div>}</Rows></Card>
          </main>
          <aside>
            <Card><div className="gitv-card-title tinted">Today's Matches</div><Rows count={matches.length}>{(i) => <div className="gitv-row gitv-match" key={i}><div className="gitv-matchline"><span><i className="gitv-line" />Team A</span><b>{i < 2 ? "0 (0)" : "00:00"}</b></div><div className="gitv-matchline"><span><i className="gitv-line" />Team B</span>{i < 2 && <b>0 (0)</b>}</div></div>}</Rows></Card>
          </aside>
        </div>
      </div>
    </div>
  );
}

export function Welcome() {
  return <main className="gitv-page"><GitvPreview /></main>;
}
