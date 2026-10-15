import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("players", "routes/players.tsx"),
  route("player/:playerId", "routes/player.tsx"),
  route("matches", "routes/matches.tsx"),
  route("match/:matchId", "routes/match.tsx"),
  route("login", "routes/login.tsx"),
  route("profile", "routes/profile.tsx"),
  route("auth/discord", "routes/auth.discord.tsx"),
] satisfies RouteConfig;
