// Shared helpers: register through the UI, mint an admin session directly.

import type { Page } from "@playwright/test";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const API = "http://localhost:8000";

export function freshEmail(prefix = "e2e") {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e4)}@example.com`;
}

/** Register a brand-new user through the login page UI and wait for the app. */
export async function registerViaUi(page: Page, email: string, password = "supersecret1") {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("/chat");
  await expectAppReady(page);
}

/** Login through the login page UI. */
export async function loginViaUi(page: Page, email: string, password = "supersecret1") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("/chat");
  await expectAppReady(page);
}

/** The app shell (user footer with Sign out) proves the auth check completed. */
export async function expectAppReady(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).waitFor({ timeout: 20_000 });
}

function readJwtSecret(): string {
  const envPath = path.resolve(__dirname, "../../api/.env");
  const text = fs.readFileSync(envPath, "utf8");
  const line = text.split(/\r?\n/).find((l) => l.startsWith("JWT_SECRET="));
  if (!line) throw new Error("JWT_SECRET not found in api/.env");
  return line.slice("JWT_SECRET=".length).trim();
}

function b64url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Mint an access token for the seeded admin account (controlled test account).
 * Resolves the admin id from the local dev sqlite DB (node:sqlite, Node >= 22).
 */
export async function mintAdminTokens(): Promise<{ access: string; email: string }> {
  const secret = readJwtSecret();
  const dbPath = path.resolve(__dirname, "../../api/bohurupi.db");
  let adminId = "";
  let email = "";
  try {
    // @ts-expect-error - node:sqlite ships with Node >= 22; @types/node@20 lacks its types
    const { DatabaseSync } = await import("node:sqlite");
    const db = new DatabaseSync(dbPath, { readOnly: true });
    const row = db.prepare("SELECT id, email FROM user WHERE role = 'admin' LIMIT 1").get() as
      | { id: string; email: string }
      | undefined;
    if (row) {
      adminId = row.id;
      email = row.email;
    }
  } catch {
    throw new Error("node:sqlite unavailable — upgrade Node to >=22 to run admin E2E");
  }
  if (!adminId) throw new Error("no admin user found in the dev DB");
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = b64url(
    JSON.stringify({ sub: adminId, type: "access", iat: now, exp: now + 3600, role: "admin" })
  );
  const sig = b64url(crypto.createHmac("sha256", secret).update(`${header}.${payload}`).digest());
  return { access: `${header}.${payload}.${sig}`, email };
}

/** Inject tokens into localStorage the same way the app stores them. */
export async function loginWithToken(page: Page, tokens: {
  access_token: string;
  refresh_token?: string;
  user: Record<string, unknown>;
}) {
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("bohurupi.auth", JSON.stringify(t));
  }, {
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token ?? "",
    user: tokens.user,
  });
}
