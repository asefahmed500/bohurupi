import { expect, test } from "@playwright/test";

import { freshEmail, registerViaUi } from "./helpers";

test.describe("authentication", () => {
  test("public landing page renders; /chat is protected", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Say anything/i })).toBeVisible();
    await expect(page).toHaveURL("/");

    // visiting the app without a session still redirects to login
    await page.goto("/chat");
    await page.waitForURL(/\/login/);
    await expect(page.getByText("Welcome back")).toBeVisible();
  });

  test("register -> app shell -> sign out -> login", async ({ page }) => {
    const email = freshEmail();
    await registerViaUi(page, email);

    // sidebar + user footer show the new account
    await expect(page.getByText(email, { exact: false }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    // sign out returns to the separate login route
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login/);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("supersecret1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL("/chat");
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  test("wrong password shows an error and does not sign in", async ({ page }) => {
    const email = freshEmail();
    await registerViaUi(page, email);
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login/);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("wrong-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Invalid email or password")).toBeVisible();
    // still on login
    await expect(page).toHaveURL(/\/login/);
  });

  test("register rejects short passwords client-side", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Email").fill(freshEmail());
    await page.getByLabel("Password", { exact: true }).fill("short");
    await page.getByRole("button", { name: "Create account" }).click();
    // browser validation keeps us on the register page
    await expect(page).toHaveURL(/\/register/);
    await expect(page.getByRole("button", { name: "Create account" })).toBeVisible();
  });

  test("forgot password is email-only and links to the reset page", async ({ page }) => {
    const email = freshEmail();
    await registerViaUi(page, email);
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login/);
    await page.getByRole("link", { name: "Forgot password?" }).click();
    await page.waitForURL(/\/forgot-password/);
    await expect(page.getByLabel("Email")).toBeVisible(); // email-only form
    await page.getByLabel("Email").fill(email);
    await page.getByRole("button", { name: "Send reset link" }).click();
    await expect(page.getByRole("link", { name: "Open your reset link" })).toBeVisible();
    await page.getByRole("link", { name: "Open your reset link" }).click();
    await page.waitForURL(/\/reset-password\?token=/);
    await page.getByLabel("New password").fill("FreshPass123!");
    await page.getByLabel("Confirm password").fill("FreshPass123!");
    await page.getByRole("button", { name: "Update password" }).click();
    await page.waitForURL(/\/login/);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("FreshPass123!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL("/chat");
  });

  test("demo dropdown signs in with one click", async ({ page }) => {
    await page.goto("/login");
    const demoSelect = page.getByLabel("Demo account");
    await expect(demoSelect).toBeVisible();
    await demoSelect.click();
    await page.getByRole("option", { name: /Demo account/ }).click();
    await page.waitForURL("/chat");
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  });
});
