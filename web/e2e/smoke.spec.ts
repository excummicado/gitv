import { expect, test, type Page } from "@playwright/test";

// Every page: it renders, logs no errors, and never scrolls sideways. Ids come from api/tests/smoke_data.py.
// Pages are found by what they show (text, roles), so their components can move around freely.

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function expectNoSideScroll(page: Page) {
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(scroll, "page scrolls sideways").toBeLessThanOrEqual(width);
}

const pages: { name: string; path: string; shows: string | RegExp; then?: (page: Page) => Promise<void> }[] = [
  { name: "home", path: "/", shows: /GITV/i },
  { name: "players", path: "/players", shows: "Aether" },
  {
    name: "player characters", path: "/player/smoke-p1", shows: "Aether",
    then: async (page) => {
      await page.getByRole("tab", { name: "Персонажи" }).click();
      await expect(page.getByText("Ху Тао").filter({ visible: true }).first()).toBeVisible();
    },
  },
  {
    name: "characters, a row open", path: "/characters", shows: "Ху Тао",
    then: async (page) => {
      await page.getByRole("button", { name: /Ху Тао/ }).first().click();
      await expect(page.getByText("по созвездиям").first()).toBeVisible();
      await expect(page.locator("#char-hutao").getByText("C6", { exact: true })).toBeVisible();
    },
  },
  { name: "match", path: "/match/smoke-m3", shows: "Dainsleif" },
  { name: "tournament", path: "/tournament/smoke-t1", shows: "Abyss Smoke Cup 1" },
];

for (const p of pages) {
  test(p.name, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(p.path);
    await expect(page.getByText(p.shows).first()).toBeVisible();
    await p.then?.(page);
    await page.waitForLoadState("networkidle");
    await expectNoSideScroll(page);
    expect(errors).toEqual([]);
  });
}

// The constellation table is a grid whose lines are display: contents; on phones its columns once slid out of
// line. Seven lines (C0–C6), each on a row of its own.
test("constellation table keeps seven rows", async ({ page }, info) => {
  test.skip(info.project.name !== "phone", "the phone layout is the one that broke");
  await page.goto("/characters");
  await page.getByRole("button", { name: /Ху Тао/ }).first().click();
  await expect(page.locator("#char-hutao").getByText("C6", { exact: true })).toBeVisible();
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll(".chars-cons-line")].map((line) =>
      [...line.children].map((c) => c.getBoundingClientRect()).filter((r) => r.width > 0).map((r) => Math.round(r.top))),
  );
  expect(rows).toHaveLength(7);
  for (const tops of rows) expect(new Set(tops).size, "a line's cells share one row").toBe(1);
  expect(new Set(rows.map((tops) => tops[0])).size, "every line on its own row").toBe(7);
});
