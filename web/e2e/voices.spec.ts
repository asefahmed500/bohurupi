import { expect, test } from "@playwright/test";

import { freshEmail, registerViaUi } from "./helpers";

test.describe("voices library", () => {
  let email: string;

  test.beforeEach(async ({ page }) => {
    email = freshEmail();
    await registerViaUi(page, email);
    await page.getByRole("link", { name: "Voices" }).click();
    await page.waitForURL(/\/voices/);
  });

  test("presets load with filters and search", async ({ page }) => {
    // many preset cards render
    await expect(page.getByText("Kokoro · Heart (F)").first()).toBeVisible({ timeout: 20_000 });
    const cards = page.locator(".grid > *");
    await expect(cards.first()).toBeVisible();

    // gender filter narrows to female only
    await page.getByLabel("Gender").click();
    await page.getByRole("option", { name: "Female" }).click();
    await expect(page.getByText("Edge English · Male").first()).toHaveCount(0);

    // search by name
    await page.getByLabel("Search voices").fill("Heart");
    await expect(page.getByText("Kokoro · Heart (F)")).toBeVisible();
  });

  test("language filter shows only bangla voices", async ({ page }) => {
    await page.getByLabel("Language").click();
    await page.getByRole("option", { name: "বাংলা" }).click();
    await expect(page.getByText("Edge বাংলা · Female")).toBeVisible();
    await expect(page.getByText("Edge English · Female")).toHaveCount(0);
  });

  test("preview button actually synthesizes audio (WS speak)", async ({ page }) => {
    const previewBtn = page.getByRole("button", { name: "Preview voice" }).first();
    await previewBtn.click();
    // a spinner replaces the icon while synthesizing, and no error toast appears
    await expect(page.getByRole("button", { name: "Stop preview" })).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByText(/Preview failed/i)).toHaveCount(0);
  });

  test("clone wizard enforces the consent gate", async ({ page }) => {
    await page.getByRole("link", { name: "Clone a voice" }).click();
    await page.waitForURL(/\/voices\/clone/);

    // continue without consent -> blocked
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText(/confirm you have the right/i)).toBeVisible();

    // consent phrase must be typed exactly
    await page.getByRole("checkbox").click();
    const phrase = await page.locator("blockquote").innerText();
    await page.getByLabel("Type the phrase exactly").fill("wrong text");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText(/Type the consent phrase exactly/i)).toBeVisible();

    // exact phrase but no consent recording -> blocked
    await page.getByLabel("Type the phrase exactly").fill(phrase.replace(/[“”]/g, ""));
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText(/Record yourself reading the consent phrase/i)).toBeVisible();
  });

  test("my voices tab is empty for a fresh user", async ({ page }) => {
    await page.getByRole("tab", { name: "My voices" }).click();
    await expect(page.getByText("No voices yet")).toBeVisible({ timeout: 15_000 });
  });
});
