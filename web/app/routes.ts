import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("players", "routes/players.tsx"),
  route("player/:playerId", "routes/player.tsx"),
  route("player/:playerId/compare/:otherId?", "routes/compare.tsx"),
  route("matches", "routes/matches.tsx"),
  route("schedule", "routes/schedule.tsx"),
  route("articles", "routes/articles.tsx"),
  route("articles/:articleId", "routes/articles.post.tsx"),
  route("news", "routes/news.redirect.tsx", { id: "news-redirect" }),
  route("news/:articleId", "routes/news.redirect.tsx", { id: "news-article-redirect" }),
  route("match/:matchId", "routes/match.tsx"),
  route("tournaments", "routes/tournaments.tsx"),
  route("characters", "routes/characters.tsx"),
  route("tournament/:tournamentId", "routes/tournament.tsx"),
  route("login", "routes/login.tsx"),
  route("profile", "routes/profile.tsx"),
  route("analytics", "routes/site-stats.tsx"),
  route("auth/discord", "routes/auth.discord.tsx"),
  route("abyss", "routes/abyss.tsx"),
  route("abyss/:phaseId", "routes/abyss.phase.tsx"),
  route("privacy", "routes/privacy.tsx"),
  route("robots.txt", "routes/robots[.]txt.ts"),
  route("sitemap.xml", "routes/sitemap[.]xml.ts"),
  // Last: every other address is the 404 page.
  route("*", "routes/not-found.tsx"),
] satisfies RouteConfig;
