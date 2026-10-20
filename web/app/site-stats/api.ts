// The analytics summary (GET /api/v1/admin/analytics), for admins.

import { authRequest } from "../auth/client";

export type DayCount = { day: string; views: number; visitors: number };
export type Analytics = {
  days: DayCount[]; views: number; visitors: number; today: DayCount; active_now: number;
  top_pages: { path: string; views: number }[]; top_sections: { path: string; views: number }[];
  top_referrers: { host: string; visits: number }[];
};

export function fetchAnalytics(days: number) {
  return authRequest<Analytics>("GET", `/admin/analytics?days=${days}`);
}
