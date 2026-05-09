import { expect, test } from "@playwright/test";

const routes = [
  { path: "/", heading: "Mission Control" },
  { path: "/scenarios", heading: "Scenarios" },
  { path: "/scenarios/scenario-1", heading: "Gold outlook" },
  { path: "/kb", heading: "Knowledge Base" },
  { path: "/kb/kb-1", heading: "KB kb-1" },
  { path: "/graph", heading: "Graph Explorer" },
  { path: "/runs", heading: "Agent Runs" },
  { path: "/runs/run-1", heading: "prediction_coordinator" },
  { path: "/calibration", heading: "Calibration" },
  { path: "/settings", heading: "Settings" },
];

test.describe("planned GUI routes", () => {
  for (const route of routes) {
    test(`${route.path} loads from mocked backend`, async ({ page }) => {
      await page.goto(route.path);
      await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
      await expect(page.getByText("Consumes")).toBeVisible();
    });
  }
});
