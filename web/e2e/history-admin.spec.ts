import { expect, test } from "@playwright/test";

import { freshEmail, loginWithToken, mintAdminTokens, registerViaUi, API } from "./helpers";

test.describe("history", () => {
  test("conversations created by the user appear and can be opened", async ({ page, request }) => {
    const email = freshEmail();
    await registerViaUi(page, email);

    // create a conversation via the API with the UI's stored token
    const tokens = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("bohurupi.auth") ?? "{}")
    );
    const created = await request.post(`${API}/conversations`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
      data: { title: "E2E history conversation", default_lang: "bn" },
    });
    expect(created.status()).toBe(201);
    const conv = await created.json();
    // touch it so updated_at is fresh
    await request.patch(`${API}/conversations/${conv.id}`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
      data: { title: "E2E history conversation" },
    });

    await page.getByRole("link", { name: "History" }).click();
    await page.waitForURL(/\/history/);
    const row = page.getByText("E2E history conversation");
    await expect(row.first()).toBeVisible({ timeout: 20_000 });

    // clicking opens THAT conversation in chat
    await row.first().click();
    await page.waitForURL("/chat");
    await expect(page.getByRole("heading", { name: "E2E history conversation" })).toBeVisible();
  });

  test("delete removes the conversation from the list", async ({ page, request }) => {
    // the app now asks for confirmation before destructive deletes
    page.on("dialog", (dialog) => void dialog.accept());
    const email = freshEmail();
    await registerViaUi(page, email);
    const tokens = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("bohurupi.auth") ?? "{}")
    );
    const created = await request.post(`${API}/conversations`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
      data: { title: "E2E delete me" },
    });
    const conv = await created.json();

    await page.getByRole("link", { name: "History" }).click();
    await page.waitForURL(/\/history/);
    await expect(page.getByText("E2E delete me")).toBeVisible({ timeout: 20_000 });

    await page.getByRole("button", { name: "Delete conversation" }).first().click();
    await expect(page.getByText("E2E delete me")).toHaveCount(0);

    // server confirms deletion
    const gone = await request.get(`${API}/conversations/${conv.id}`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    expect(gone.status()).toBe(404);
  });
});

test.describe("admin", () => {
  test("non-admin has no Admin nav link and the /admin route is gated", async ({ page }) => {
    const email = freshEmail();
    await registerViaUi(page, email);

    // the sidebar never offers Admin to a plain user (RBAC in the UI)
    await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

    // direct URL access is still gated client-side, and the API returns 403
    await page.goto("/admin");
    await expect(page.getByText("Admin access required.")).toBeVisible();
  });

  test("admin sees engines, users with management controls, and moderation tab", async ({
    page,
  }) => {
    const { access, email } = await mintAdminTokens();
    await loginWithToken(page, {
      access_token: access,
      user: { email, name: "Admin", role: "admin", plan: "free", id: "", created_at: "" },
    });
    await page.goto("/admin");
    await page.waitForURL(/\/admin/);

    // overview stat cards render
    await expect(page.getByText("TTS minutes (30d)")).toBeVisible({ timeout: 20_000 });

    // engines tab lists kokoro + edge with toggles
    await page.getByRole("tab", { name: "Engines" }).click();
    await expect(page.getByText("kokoro")).toBeVisible();
    await expect(page.getByText("edge")).toBeVisible();
    await expect(page.getByRole("switch", { name: "Toggle kokoro" })).toBeVisible();

    // users tab shows role/plan selects and active switches
    await page.getByRole("tab", { name: "Users" }).click();
    await expect(page.getByText(email).first()).toBeVisible();
    await expect(page.getByRole("switch", { name: /Active for/ }).first()).toBeVisible();

    // moderation tab renders (empty state for a clean DB)
    await page.getByRole("tab", { name: /Moderation/ }).click();
    await expect(page.getByText("No voices waiting for review.")).toBeVisible();
  });
});
