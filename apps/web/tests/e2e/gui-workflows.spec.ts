import { expect, test } from "@playwright/test";

test("scenario creation redirects to persisted detail page", async ({ page }) => {
  await page.goto("/scenarios");
  await page.getByPlaceholder(/I want to understand/).fill("I want to forecast whether the browser workflow persists over the next six months.");
  await page.getByRole("button", { name: "Draft scenario" }).click();
  await expect(page.getByLabel("Draft scenario fields")).toBeVisible();
  await page.getByRole("button", { name: "Create scenario" }).click();
  await expect(page).toHaveURL(/\/scenarios\/scenario-created$/, { timeout: 20_000 });
  await expect(page.getByRole("heading", { level: 1, name: "Created in browser" })).toBeVisible();
});

test("scenario detail queues a workflow phase and resolves feedback", async ({ page }) => {
  await page.goto("/scenarios/scenario-1");
  await page.getByText("Queue persisted phase job").click();
  await page.getByRole("button", { name: "Queue phase" }).click();
  await expect(page).toHaveURL(/job_id=job-/);

  await page.getByPlaceholder("Actual outcome").fill("Base case happened");
  await page.getByText("Resolve prediction with feedback").click();
  await page.getByRole("button", { name: "Run feedback" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Latest prediction" })).toBeVisible();
});

test("KB search filters round-trip and entry detail exposes related records", async ({ page }) => {
  await page.goto("/kb");
  await page.getByPlaceholder("Keyword search").fill("central banks");
  await page.getByRole("textbox", { name: "Topic", exact: true }).fill("gold");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/topic=gold/);
  await expect(page.getByText("Central banks continue buying gold.")).toBeVisible();

  await page.goto("/kb/kb-1");
  await expect(page.getByText("Linked scenarios, graph, and predictions")).toBeVisible();
  await expect(page.getByText("Gold outlook")).toBeVisible();
});

test("graph selection, layout controls, merge inbox, and edge edit persistence use backend mutations", async ({ page }) => {
  await page.goto("/graph");
  await expect(page.locator('[data-testid="reactflow-graph-canvas"]')).toBeVisible();
  await page.getByRole("combobox").filter({ hasText: /Radial layout|Large-graph grid|Type layers/ }).selectOption("grid");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/layout=grid/);
  await expect(page.getByText("Fed policy · pending")).toBeVisible();
  await page.getByText("Fed policy · pending").click();
  await expect(page.getByText("Duplicate policy aliases")).toBeVisible();

  await page.getByRole("link", { name: /Fed policy/ }).first().click();
  await expect(page).toHaveURL(/selected_node=node-1/);
  await expect(page.getByRole("heading", { level: 2, name: "Selected node detail" })).toBeVisible();

  await page.goto("/graph?selected_edge=edge-1");
  await page.getByText("Edit edge metadata").click();
  await page.getByRole("spinbutton").nth(0).fill("0.85");
  await page.getByRole("button", { name: "Persist edge changes" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Selected edge detail" })).toBeVisible();
});

test("run retry and settings validation surfaces are wired", async ({ page }) => {
  await page.goto("/runs/run-1");
  await page.getByText("Retry / re-dispatch run").click();
  await page.getByRole("button", { name: "Retry through backend" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Model invocations" })).toBeVisible();

  await page.goto("/scenarios/scenario-1");
  await expect(page.getByRole("link", { name: "HTML report" })).toHaveAttribute("href", /format=html/);
  await expect(page.getByRole("link", { name: "JSON export" })).toHaveAttribute("href", /format=json/);
  await page.getByPlaceholder("Actual outcome").fill("Base case happened");
  await page.locator('select[name="correction_action"]').selectOption("modify_edge");
  await page.getByPlaceholder("Target node/edge ID").fill("edge-1");
  await page.getByText("Resolve prediction with feedback").click();
  await page.getByRole("button", { name: "Run feedback" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Latest prediction" })).toBeVisible();

  await page.goto("/settings");
  await page.getByLabel("fast").fill("mock/updated-fast");
  await page.getByRole("button", { name: "Save model profiles" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Runtime-editable model profiles" })).toBeVisible();
});
