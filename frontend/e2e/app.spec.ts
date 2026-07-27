import { expect, test } from "@playwright/test";

test.describe("Interview Tracker E2E", () => {
  test("loads dashboard and connects over WebSocket", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Interview Tracker" })).toBeVisible();
    await expect(page.getByText("Live connection active")).toBeVisible();
    await expect(page.getByText("Company 14")).toBeVisible();
  });

  test("filters seeded records", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByLabel("Search").fill("Company 01");
    await expect(page.getByText("Company 01")).toBeVisible();
    await expect(page.getByText("Company 00")).toHaveCount(0);
  });

  test("persists settings without touching OS scheduler", async ({ page }) => {
    await page.goto("/settings");
    await page.getByLabel("Email filter").fill("e2e@example.com");
    await page.getByRole("button", { name: "Save and apply schedule" }).click();
    await expect(page.getByRole("status")).toContainText("Saved");
    await page.goto("/settings");
    await expect(page.getByLabel("Email filter")).toHaveValue("e2e@example.com");
  });

  test("runs manual scan with progress modal", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "Scan Gmail now" }).click();
    await expect(page.getByRole("dialog", { name: "Gmail scan progress" })).toBeVisible();
    await expect(page.getByText(/threads/i)).toBeVisible({ timeout: 45_000 });
  });
});
