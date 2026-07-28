import { defineConfig } from "@playwright/test";

/**
 * 视觉回归（规划 Phase 6 / §15）：四档视口 × 亮/暗 × reduced motion。
 * 页面数据由 e2e/stub-api.ts 的契约 fixture 拦截提供，不依赖后端进程。
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 4,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  expect: {
    // dev server 冷启动时 lazy 路由 chunk 的按需转换可能超过默认 5s
    timeout: 15_000,
    toHaveScreenshot: {
      // 流式/动画场景允许少量像素差
      maxDiffPixelRatio: 0.01,
    },
  },
  projects: [
    { name: "light-1600", use: { viewport: { width: 1600, height: 1000 } } },
    { name: "light-1366", use: { viewport: { width: 1366, height: 768 } } },
    { name: "light-1024", use: { viewport: { width: 1024, height: 768 } } },
    {
      name: "mobile-390",
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
    {
      name: "dark-1366",
      use: {
        viewport: { width: 1366, height: 768 },
        storageState: {
          cookies: [],
          origins: [
            {
              origin: "http://localhost:5173",
              localStorage: [
                {
                  name: "study-ai-ui",
                  value: JSON.stringify({ state: { theme: "dark", sidebarCollapsed: false }, version: 0 }),
                },
              ],
            },
          ],
        },
      },
    },
    {
      name: "reduced-motion-1366",
      use: { viewport: { width: 1366, height: 768 }, contextOptions: { reducedMotion: "reduce" } },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 90_000,
  },
});
