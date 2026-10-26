import { test, expect } from "@playwright/test";

const firstCourse = "UI fixture - Retrieval interaction test";
const secondCourse = "UI fixture - Second course";

async function openPanel(page, id = 1) {
  await page.goto(`/courses/${id}`);
  await expect(page.getByRole("heading", {
    name: id === 1 ? firstCourse : secondCourse, exact: true,
  })).toBeVisible();
  const panel = page.locator(".retrieval-debug");
  await panel.locator("summary").click();
  await expect(panel.getByLabel("Question", { exact: true })).toBeVisible();
  return panel;
}

async function search(panel, query) {
  await panel.getByLabel("Question", { exact: true }).fill(query);
  await panel.getByRole("button", { name: "Search passages", exact: true }).click();
}

test("home opens a real Course route and the debug panel toggles with the keyboard", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: `Open ${firstCourse}`, exact: true }).click();
  await expect(page).toHaveURL(/\/courses\/1$/);
  const panel = page.locator(".retrieval-debug");
  await expect(panel.getByLabel("Question", { exact: true })).toBeHidden();
  await panel.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByLabel("Question", { exact: true })).toBeVisible();
  await panel.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByLabel("Question", { exact: true })).toBeHidden();
});

test("blank questions are rejected locally without sending a search request", async ({ page }) => {
  const panel = await openPanel(page);
  const sent = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/courses/1/search")) sent.push(request);
  });
  await search(panel, "   ");
  await expect(panel.getByRole("alert")).toHaveText("Enter a question to search.");
  expect(sent).toHaveLength(0);
});

test("success trims the question, disables controls while loading, and renders ordered evidence", async ({ page }) => {
  const panel = await openPanel(page);
  const requestPromise = page.waitForRequest((request) => request.url().endsWith("/courses/1/search"));
  await search(panel, "  Why doesn't DFS find the shortest route?  ");
  await expect(panel.getByRole("button", { name: "Searching…" })).toBeDisabled();
  await expect(panel.getByLabel("Question", { exact: true })).toBeDisabled();
  await expect(panel.getByLabel("Top K")).toBeDisabled();
  const request = await requestPromise;
  expect(request.method()).toBe("POST");
  expect(request.postDataJSON()).toEqual({
    query: "Why doesn't DFS find the shortest route?", top_k: 5,
  });
  const hits = panel.locator(".retrieval-results > li");
  await expect(hits).toHaveCount(5);
  await expect(hits.nth(0)).toContainText("#1 · MIT6_006S20_lec10.pdf");
  await expect(hits.nth(0)).toContainText("Page 2 · Score 0.8754");
  await expect(hits.nth(0)).toContainText("Chunk #100 · Document #1");
  await expect(hits.nth(1)).toContainText("Page unavailable");
  await expect(hits.nth(4)).toContainText("#5");
  await expect(panel.getByText(/not answer confidence/)).toBeVisible();
  await expect(panel.getByLabel("Question", { exact: true })).toBeEnabled();
  expect(await hits.nth(0).locator("pre").textContent()).toContain("\nReceived query:");
});

test("Top K changes are sent to the API and replace the old result set", async ({ page }) => {
  const panel = await openPanel(page);
  await panel.getByLabel("Top K").selectOption("3");
  await search(panel, "Check top k");
  await expect(panel.locator(".retrieval-results > li")).toHaveCount(3);
  await expect(panel.locator("pre").first()).toContainText("Received top_k: 3");
  await panel.getByLabel("Top K").selectOption("10");
  await panel.getByRole("button", { name: "Search passages", exact: true }).click();
  await expect(panel.locator(".retrieval-results > li")).toHaveCount(7);
  await expect(panel.locator("pre").first()).toContainText("Received top_k: 10");
  await expect(panel.locator(".retrieval-results > li").last()).toContainText("Score -0.2046");
});

test("question input enforces the 2000-character limit", async ({ page }) => {
  const panel = await openPanel(page);
  const question = panel.getByLabel("Question", { exact: true });
  await expect(question).toHaveAttribute("maxlength", "2000");
  await question.fill("x".repeat(2050));
  await expect(question).toHaveValue("x".repeat(2000));
});

test("empty candidates clear old results and explain the processing/backfill requirement", async ({ page }) => {
  const panel = await openPanel(page);
  await search(panel, "Show initial results");
  await expect(panel.locator(".retrieval-results > li")).toHaveCount(5);
  await search(panel, "__empty__");
  await expect(panel.getByRole("status")).toContainText("No searchable passages returned.");
  await expect(panel.getByRole("status")).toContainText("embeddings");
  await expect(panel.locator(".retrieval-results > li")).toHaveCount(0);
  await expect(panel.locator(".retrieval-query")).toContainText("__empty__");
});

for (const [status, detail] of [
  [404, "Course not found"],
  [422, "UI fixture validation error"],
  [503, "Retrieval service unavailable"],
]) {
  test(`HTTP ${status} is visible and a later successful search recovers`, async ({ page }) => {
    const panel = await openPanel(page);
    await search(panel, `__${status}__`);
    await expect(panel.getByRole("alert")).toHaveText(`Error ${status}: ${detail}`);
    await expect(panel.getByRole("button", { name: "Search passages", exact: true })).toBeEnabled();
    await expect(panel.locator(".retrieval-results > li")).toHaveCount(0);
    await search(panel, "Retry after service error");
    await expect(panel.locator(".retrieval-results > li")).toHaveCount(5);
    await expect(panel.getByRole("alert")).toHaveCount(0);
  });
}

test("a failed network request is visible and retry works", async ({ page }) => {
  const panel = await openPanel(page);
  await page.route("**/courses/1/search", (route) => route.abort("failed"));
  await search(panel, "Network test");
  await expect(panel.getByRole("alert")).toContainText("Cannot reach retrieval.");
  await page.unroute("**/courses/1/search");
  await search(panel, "Network recovered");
  await expect(panel.locator(".retrieval-results > li")).toHaveCount(5);
});

test("leaving a pending search aborts it and a second Course has fresh state", async ({ page }) => {
  const panel = await openPanel(page);
  await search(panel, "Pending search");
  await expect(panel.getByRole("button", { name: "Searching…" })).toBeVisible();
  const failedRequest = page.waitForEvent("requestfailed", {
    predicate: (request) => request.url().endsWith("/courses/1/search"),
  });
  await page.getByRole("link", { name: "All courses", exact: true }).click();
  await failedRequest;
  await page.getByRole("link", { name: `Open ${secondCourse}`, exact: true }).click();
  await expect(page.getByRole("heading", { name: secondCourse, exact: true })).toBeVisible();
  const nextPanel = page.locator(".retrieval-debug");
  await nextPanel.locator("summary").click();
  await expect(nextPanel.getByLabel("Question", { exact: true })).toHaveValue("");
  await expect(nextPanel.locator(".retrieval-results > li")).toHaveCount(0);
  await search(nextPanel, "Second course question");
  await expect(nextPanel.getByRole("status")).toContainText("No searchable passages");
});

test("PDF names and passage markup are rendered as plain text", async ({ page }) => {
  const panel = await openPanel(page);
  await search(panel, "<img src=x onerror=alert(1)>");
  await expect(panel.locator(".retrieval-results > li")).toHaveCount(5);
  await expect(panel.locator("pre").first()).toContainText("<img src=x onerror=alert(1)>");
  await expect(panel.locator("pre img")).toHaveCount(0);
});

for (const width of [375, 768, 1280]) {
  test(`results stay within the viewport at ${width}px including long names and unbroken text`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const panel = await openPanel(page);
    await panel.getByLabel("Top K").selectOption("3");
    await search(panel, "Responsive layout test");
    await expect(panel.locator(".retrieval-results > li")).toHaveCount(3);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const screenshot = testInfo.outputPath(`retrieval-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach(`retrieval-${width}`, { path: screenshot, contentType: "image/png" });
  });
}
