import { expect, test } from "@playwright/test";

import { stubApi, stubChatStream, stubStudyMaterialsStream } from "./stub-api";

/**
 * 视觉回归基线（规划 §15 视觉验收）。
 * 覆盖：四档视口（1600×1000 / 1366×768 / 1024×768 / 390×844）、亮色/深色、reduced motion。
 * 首跑使用 --update-snapshots 生成基线；之后 diff 超过 1% 像素视为回归。
 */

test.beforeEach(async ({ page }) => {
  await stubApi(page);
});

/** 等待页面主要内容就绪并停止动画，保证截图稳定。 */
async function settle(page: import("@playwright/test").Page) {
  await page.waitForLoadState("networkidle");
  await freezeMotion(page);
}

async function freezeMotion(page: import("@playwright/test").Page) {
  await page.addStyleTag({
    content: "*, *::before, *::after { animation: none !important; transition: none !important; }",
  });
}

async function startStudyMaterials(
  page: import("@playwright/test").Page,
  mode: "running" | "done" | "failed",
) {
  await stubStudyMaterialsStream(page, mode);
  await page.goto("/materials");
  await page.getByRole("textbox").fill("函数单调性");
  await page.getByRole("button", { name: "开始生成" }).click();
}

test("登录页", async ({ page }) => {
  await page.goto("/login");
  await settle(page);
  await expect(page).toHaveScreenshot("login.png", { fullPage: true });
});

test("首页 Intent Workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("今天想学习什么？")).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("home.png", { fullPage: true });
});

test("对话空态（模式提示 + 输入舱）", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByText("开始新的学习对话")).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("chat-empty.png");
});

test("对话会话（Markdown / 公式 / 表格 / 代码 + 工具标记）", async ({ page }) => {
  await page.goto("/chat/101");
  await expect(page.getByText("诱导公式速记")).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("chat-conversation.png");
});

/** Chat 流式中态（视觉规划遗留缺口）：拦截 /api/chat 保持流打开，稳定停在进行中状态。 */
async function startChatStream(page: import("@playwright/test").Page, mode: "thinking" | "tools-running") {
  await stubChatStream(page, mode);
  await page.goto("/chat/101");
  await expect(page.getByText("诱导公式速记")).toBeVisible();
  await page.getByRole("textbox").fill("再出几道三角函数练习题");
  await page.getByRole("button", { name: "发送" }).click();
}

test("对话流式中态：思考文本", async ({ page }) => {
  await startChatStream(page, "thinking");
  await expect(page.getByText("我先检索题库中匹配的题目")).toBeVisible();
  await freezeMotion(page);
  await expect(page).toHaveScreenshot("chat-streaming-thinking.png");
});

test("对话流式中态：并行工具执行", async ({ page }) => {
  await startChatStream(page, "tools-running");
  await expect(page.getByText("并行执行")).toBeVisible();
  await expect(page.getByText("网络搜索")).toBeVisible();
  await freezeMotion(page);
  await expect(page).toHaveScreenshot("chat-streaming-tools.png");
});

test("组卷工作室", async ({ page }) => {
  await page.goto("/compose");
  await expect(page.locator("main").getByRole("heading", { name: "组卷工作室" })).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("compose.png", { fullPage: true });
});

test("题库", async ({ page }) => {
  await page.goto("/library");
  await settle(page);
  await expect(page).toHaveScreenshot("library.png", { fullPage: true });
});

test("试卷库", async ({ page }) => {
  await page.goto("/papers");
  await expect(page.getByText("高一数学三角函数单元卷").first()).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("papers.png", { fullPage: true });
});

test("学习资料空态", async ({ page }) => {
  await page.goto("/materials");
  await expect(page.getByText("说出想学的主题，")).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("materials.png", { fullPage: true });
});

test("学习资料运行态", async ({ page }) => {
  await startStudyMaterials(page, "running");
  await expect(page.getByText("联网搜索相关学习资料")).toBeVisible();
  await freezeMotion(page);
  await expect(page).toHaveScreenshot("materials-running.png");
});

test("学习资料完成态", async ({ page }) => {
  await startStudyMaterials(page, "done");
  await expect(page.getByRole("heading", { name: "函数单调性 · 自学讲义" })).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("materials-done.png");
});

test("学习资料失败恢复态", async ({ page }) => {
  await startStudyMaterials(page, "failed");
  await expect(page.getByRole("heading", { name: "生成失败" })).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("materials-failed.png");
});

test("任务中心", async ({ page }) => {
  await page.goto("/tasks");
  await expect(page.getByText("高一数学三角函数单元卷").first()).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("tasks.png", { fullPage: true });
});

test("设置 Quiet Form", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.locator("main").getByRole("heading", { name: "设置" })).toBeVisible();
  await settle(page);
  await expect(page).toHaveScreenshot("settings.png", { fullPage: true });
});
