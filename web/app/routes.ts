import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("players", "routes/players.tsx"),
  route("player/:playerId", "routes/player.tsx"),
  route("player/:playerId/compare/:otherId?", "routes/compare.tsx"),
  route("matches", "routes/matches.tsx"),
  route("schedule", "routes/schedule.tsx"),
  route("match/:matchId", "routes/match.tsx"),
  route("tournaments", "routes/tournaments.tsx"),
  route("characters", "routes/characters.tsx"),
  route("tournament/:tournamentId", "routes/tournament.tsx"),
  route("login", "routes/login.tsx"),
  route("profile", "routes/profile.tsx"),
  route("analytics", "routes/site-stats.tsx"),
  route("auth/discord", "routes/auth.discord.tsx"),
] satisfies RouteConfig;
