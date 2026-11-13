// Bets for points on the announced matches (api/app/routers/bets.py, rules in api/app/services/bets.py). While they
// are tested, only the super admin and the members marked as bet testers get them.

import { authRequest } from "../auth/client";

export type Rules = {
  start: number; daily: number; streak_days: number; streak_bonus: number; min_bet: number; max_per_match: number; handicap: number[];
};
// bonus: given by this very visit (0 when today's was given already); can_bet: false for a Discord account too young
export type Wallet = { month: string; balance: number; handicap: number; streak: number; bonus: number; can_bet: boolean; rules: Rules };
export type BetStatus = "pending" | "won" | "lost" | "refunded";
export type MyBet = { amount: number; odds: number; payout: number; status: BetStatus };
// odds: null when no bets are taken on the match; stake: points bet on the player by everyone
export type Side = { id: string | null; name: string; elo: number | null; odds: number | null; stake: number };
// open: bets are taken; no_elo: never were; started: waits for its result; settled; void: bets returned
export type MarketState = "open" | "no_elo" | "started" | "settled" | "void";
export type Market = {
  id: number; tournament_title: string; starts_at: string; players: [Side, Side]; state: MarketState;
  winner: 0 | 1 | null; my_side: 0 | 1 | null; my_bets: MyBet[]; can_settle: boolean;
};
export type HistoryRow = {
  tournament_title: string; player1: string; player2: string; starts_at: string; side: 0 | 1;
  amount: number; odds: number; payout: number; status: BetStatus; created_at: string;
};
export type Standing = { place: number; nickname: string; balance: number; me: boolean };
export type Result = "player1" | "player2" | "void";

// The visit gives the day's bonus, so the menu makes it on every page; kept for a minute so it isn't asked each time.
let kept: { at: number; wallet: Promise<Wallet> } | null = null;

export function visit(fresh = false): Promise<Wallet> {
  if (fresh || !kept || Date.now() - kept.at > 60_000) {
    const wallet = authRequest<Wallet>("POST", "/bets/visit");
    kept = { at: Date.now(), wallet };
    wallet.catch(() => { kept = null; });
  }
  return kept.wallet;
}

export function fetchMarkets() {
  return authRequest<Market[]>("GET", "/bets/markets");
}

export function fetchMyBets() {
  return authRequest<HistoryRow[]>("GET", "/bets/mine");
}

export function fetchLeaderboard() {
  return authRequest<Standing[]>("GET", "/bets/leaderboard");
}

// odds: the odds shown to the member; if they have dropped since, the API refuses and the page shows the new ones.
export function placeBet(matchId: number, side: 0 | 1, amount: number, odds: number) {
  return authRequest<Market>("POST", `/bets/markets/${matchId}/bets`, { side, amount, odds });
}

export function setResult(matchId: number, result: Result) {
  return authRequest<Market>("PUT", `/bets/markets/${matchId}/result`, { result });
}
