import { expect, test, type Page } from "@playwright/test";

/**
 * The whole product loop, through the real UI against a real engine:
 * ask → decide → learn a rule → accept → auto-approve with receipt → flag → rule pauses.
 */
test.describe.configure({ mode: "serial" });

const invoice = {
  agent: "invoice-bot", platform: "n8n", action: "send_email", target: { type: "invoice" },
  amount: { value: 1200 }, recipient: { id: "billing@acme-dental.com", known: true },
  reversible: false, environment: "production", client: "acme-dental",
};
const forcePush = {
  agent: "claude-code", platform: "claude_code", action: "bash", reversible: false, environment: "production",
  context: { command: "git push --force origin main" },
};

let errors: string[] = [];
function watchErrors(page: Page) {
  errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
}

test.beforeAll(async ({ request }) => {
  // one invoice slightly different from the learned shape (new recipient) so it waits for a person
  for (const body of [{ ...invoice, recipient: { id: "new@acme-dental.com", known: false } }, forcePush]) {
    const r = await request.post("/v1/requests", { data: body });
    expect(r.status()).toBe(201);
    expect((await r.json()).status).toBe("pending");
  }
});

test("inbox shows pending requests with risk, command and chain status", async ({ page }) => {
  watchErrors(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/inbox$/);
  await expect(page.getByText("git push --force origin main")).toBeVisible();
  await expect(page.locator("[data-req]")).toHaveCount(2);
  await expect(page.getByTestId("chain-status")).toContainText("Chain OK");
  await expect(page.getByRole("link", { name: /Inbox\s*2/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test("approve and deny clear the inbox and are stored", async ({ page, request }) => {
  await page.goto("/inbox");
  const push = page.locator("[data-req]", { hasText: "git push" });
  await push.locator("[data-deny]").click();
  await expect(push).toHaveCount(0);
  await page.locator("[data-req]").first().locator("[data-approve]").click();
  await expect(page.getByText("All clear.")).toBeVisible();
  const recent = await (await request.get("/v1/requests?limit=2")).json();
  expect(recent.map((r: { status: string }) => r.status).sort()).toEqual(["approved", "denied"]);
});

test("history lists decisions and filters", async ({ page }) => {
  await page.goto("/history");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "By a person" }).click();
  await expect(page.locator("tbody")).toContainText("denied");
});

test("find rules → backtest → accept → next invoice auto-approved with receipt", async ({ page, request }) => {
  await page.goto("/rules");
  await page.getByRole("button", { name: "Find rules now" }).click();
  const r1 = page.locator('[data-rule="R-1"]');
  await expect(r1).toContainText("proposed");
  await expect(r1).toContainText("approvals");

  await r1.getByRole("button", { name: "Backtest" }).click();
  await expect(r1.getByTestId("backtest")).toContainText("Passed");

  await r1.getByRole("button", { name: "Accept" }).click();
  await expect(r1).toContainText("active");

  const created = await (await request.post("/v1/requests", { data: invoice })).json();
  expect(created.status).toBe("auto_approved");
  expect(created.receipt.rule).toBe("R-1");
  expect(created.receipt.evidence.approvals).toBeGreaterThanOrEqual(10);
});

test("'Wrong' on an automatic approval pauses the rule (drift watch)", async ({ page, request }) => {
  await page.goto("/history");
  await page.getByRole("button", { name: "Automatic" }).click();
  await page.locator("[data-flag]").first().click();
  await expect(page.getByText(/paused/)).toBeVisible();
  const rules = await (await request.get("/v1/rules")).json();
  expect(rules.find((r: { id: string }) => r.id === "R-1").status).toBe("paused");
});

test("hard lines can be added and removed", async ({ page }) => {
  await page.goto("/hard-lines");
  await page.getByLabel("Field").fill("amount.value");
  await page.getByLabel("Operator").selectOption("gte");
  await page.getByLabel("Value").fill("100000");
  await page.getByLabel("Description").fill("Big money always asks");
  await page.getByRole("button", { name: "Add line" }).click();
  const line = page.locator("article", { hasText: "Big money always asks" });
  await expect(line).toBeVisible();
  await line.getByRole("button", { name: "Remove" }).click();
  await expect(line).toHaveCount(0);
});

test("insights and audit render; audit chain verified", async ({ page }) => {
  await page.goto("/insights");
  await expect(page.getByText("requests from your agents")).toBeVisible();
  await expect(page.locator("tbody")).toContainText("invoice-bot");
  await page.goto("/audit");
  await expect(page.getByRole("heading", { name: "Hash chain verified" })).toBeVisible();
});

test("theme toggle persists across reloads", async ({ page }) => {
  await page.goto("/inbox");
  const before = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.getByRole("button", { name: /Switch to/ }).click();
  await page.reload();
  const after = await page.evaluate(() => document.documentElement.dataset.theme);
  expect(after).not.toBe(before);
});

test("phone width: no horizontal scroll, no JS errors", async ({ page }) => {
  watchErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/inbox", "/history", "/rules", "/hard-lines", "/insights", "/audit"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(overflow, `${path} overflows`).toBe(false);
  }
  expect(errors).toEqual([]);
});
