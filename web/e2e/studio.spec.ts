import { expect, test } from "@playwright/test";

import { freshEmail, registerViaUi } from "./helpers";

test.describe("voice studio", () => {
  test("preview works standalone — no chat required (regression: studio was gated on an open chat)", async ({
    page,
  }) => {
    const email = freshEmail();
    await registerViaUi(page, email);

    // go straight to the studio without ever opening a chat conversation
    await page.getByRole("link", { name: "Studio" }).click();
    await page.waitForURL(/\/studio/);

    await page.getByRole("button", { name: "Preview" }).click();
    // done frame produces the engine badge — proves the full speak pipeline ran
    await expect(page.getByText(/^kokoro$|^edge$/).first()).toBeVisible({
      timeout: 60_000,
    });
    // an <audio> player appears for the rendered asset
    await expect(page.locator("audio").first()).toBeVisible({ timeout: 20_000 });
  });

  test("controls update values", async ({ page }) => {
    const email = freshEmail();
    await registerViaUi(page, email);
    await page.getByRole("link", { name: "Studio" }).click();
    await page.waitForURL(/\/studio/);

    const speedSlider = page.getByLabel("Speed");
    await expect(speedSlider).toBeVisible();
    const sentence = page.getByLabel("Sentence");
    await sentence.fill("Custom studio sentence for testing.");
    await expect(sentence).toHaveValue("Custom studio sentence for testing.");
    await page.getByLabel("Emotion / style").click();
    await page.getByRole("option", { name: "warm" }).click();
    await expect(page.getByLabel("Emotion / style")).toContainText("warm");
  });
});
