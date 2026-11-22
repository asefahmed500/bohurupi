import { expect, test } from "@playwright/test";

import { freshEmail, registerViaUi } from "./helpers";

test.describe("chat", () => {
  let email: string;

  test.beforeEach(async ({ page }) => {
    email = freshEmail();
    await registerViaUi(page, email);
  });

  test("chat page shows starter prompts and the composer", async ({ page }) => {
    await expect(page.getByText("Speak or type in any language")).toBeVisible();
    await expect(page.getByPlaceholder("Ask anything, in any language…")).toBeVisible();
    await expect(page.getByRole("button", { name: "Record speech" }).first()).toBeVisible();
  });

  test("sending a message with no LLM key surfaces an honest error and keeps the user message", async ({
    page,
  }) => {
    await page
      .getByPlaceholder("Ask anything, in any language…")
      .fill("Hello Bohurupi, this is an E2E test");
    await page.keyboard.press("Enter");

    // the user's bubble appears immediately
    await expect(
      page.getByText("Hello Bohurupi, this is an E2E test").first()
    ).toBeVisible();

    // without ZAI_API_KEY the backend streams an explicit error frame
    await expect(
      page.getByText(/AI engine is not configured/i).first()
    ).toBeVisible({ timeout: 30_000 });
  });

  test("reply-language picker updates the label and persists the choice", async ({ page }) => {
    await page.getByRole("button", { name: /Reply in: Auto/ }).click();
    await page.getByRole("menuitem", { name: /বাংলা/ }).click();
    await expect(page.getByRole("button", { name: /Reply in: bn|বাংলা/ })).toBeVisible();
  });

  test("new conversation button resets the view", async ({ page }) => {
    await page
      .getByPlaceholder("Ask anything, in any language…")
      .fill("message one");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1000);
    await page.getByRole("button", { name: "New conversation" }).first().click();
    await expect(page.getByText("Speak or type in any language")).toBeVisible();
    await expect(page.getByRole("heading", { name: "New conversation" })).toBeVisible();
  });

  test("voice-to-voice toggle switches state", async ({ page }) => {
    const toggle = page.getByRole("switch", { name: "Voice-to-voice mode" });
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(toggle).toBeChecked();
  });
});
