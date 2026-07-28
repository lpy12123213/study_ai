import { describe, expect, it } from "vitest";

import { APP_ROUTES, NAV_GROUPS, bottomNavItems, contentModeForPath, navGroups, routeTitle } from "../catalog";

describe("route catalog", () => {
  it("路由 id 全局唯一且 path 不重复", () => {
    const ids = APP_ROUTES.map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
    const paths = APP_ROUTES.map((r) => r.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("navGroups 按组顺序与组内 order 输出导航项", () => {
    const groups = navGroups();
    expect(groups.map((g) => g.label)).toEqual(NAV_GROUPS.map((g) => g.label));
    expect(groups.find((g) => g.id === "create")?.items.map((i) => i.to)).toEqual([
      "/chat",
      "/compose",
      "/materials",
      "/deepthink",
    ]);
    // 详情页不出现在导航中
    expect(groups.flatMap((g) => g.items.map((i) => i.to))).not.toContain("/papers/:id");
  });

  it("routeTitle 解析列表页与详情页标题", () => {
    expect(routeTitle("/")).toBe("工作台");
    expect(routeTitle("/chat")).toBe("对话");
    expect(routeTitle("/chat/conv-1")).toBe("对话");
    expect(routeTitle("/papers")).toBe("试卷库");
    expect(routeTitle("/papers/208")).toBe("试卷详情");
    expect(routeTitle("/materials")).toBe("学习资料");
    expect(routeTitle("/materials/12")).toBe("资料详情");
    expect(routeTitle("/settings")).toBe("设置");
  });

  it("routeTitle 未命中时回退产品名", () => {
    expect(routeTitle("/no-such-page")).toBe("Study AI");
  });

  it("contentMode：对话与资料生成为 conversation，组卷/题库/任务为 workspace，其余默认 document", () => {
    expect(contentModeForPath("/chat")).toBe("conversation");
    expect(contentModeForPath("/chat/conv-1")).toBe("conversation");
    expect(contentModeForPath("/materials")).toBe("conversation");
    expect(contentModeForPath("/materials/12")).toBe("workspace");
    expect(contentModeForPath("/compose")).toBe("workspace");
    expect(contentModeForPath("/library")).toBe("workspace");
    expect(contentModeForPath("/tasks")).toBe("workspace");
    expect(contentModeForPath("/")).toBe("document");
    expect(contentModeForPath("/settings")).toBe("document");
    expect(contentModeForPath("/no-such-page")).toBe("document");
  });

  it("底部主导航引用均存在且带 nav 元信息", () => {
    const items = bottomNavItems();
    expect(items.map((i) => i.to)).toEqual(["/", "/chat", "/compose", "/library", "/settings"]);
    for (const item of items) {
      expect(item.label).toBeTruthy();
      expect(item.icon).toBeTruthy();
    }
  });
});
