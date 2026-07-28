import { describe, expect, it } from "vitest";

import {
  extractStudySources,
  studyToolDisplayName,
  studyToolIntent,
  summarizeStudyToolResult,
} from "../tool-adapters";
import { inferStageFromTool, studyStageFromFailure, studyStageFromWorkflow } from "../stages";

describe("stages：工具 → 阶段推断", () => {
  it("检索类工具归 research，写作/审查/导出各归其位", () => {
    expect(inferStageFromTool("split_knowledge_points")).toBe("plan");
    expect(inferStageFromTool("web_search_knowledge")).toBe("research");
    expect(inferStageFromTool("research_knowledge_point")).toBe("research");
    expect(inferStageFromTool("aggregate_knowledge")).toBe("aggregate");
    expect(inferStageFromTool("generate_study_material")).toBe("write");
    expect(inferStageFromTool("critique_draft")).toBe("review");
    expect(inferStageFromTool("export_study_markdown")).toBe("export");
    expect(inferStageFromTool("未知工具")).toBe("");
  });

  it("workflow_stage 与 legacy 失败标签映射", () => {
    expect(studyStageFromWorkflow("draft")).toBe("write");
    expect(studyStageFromWorkflow("revise")).toBe("review");
    expect(studyStageFromWorkflow("accept")).toBe("export");
    expect(studyStageFromFailure("search")).toBe("research");
    expect(studyStageFromFailure("export")).toBe("export");
    expect(studyStageFromFailure("未知")).toBe("");
  });
});

describe("tool-adapters：显示名与意图", () => {
  it("已知工具返回中文名，未知工具回退原名", () => {
    expect(studyToolDisplayName("web_search_knowledge")).toBe("联网搜索相关学习资料");
    expect(studyToolDisplayName("custom_tool")).toBe("custom_tool");
  });

  it("意图从参数推导并截断", () => {
    expect(studyToolIntent("web_search_knowledge", { queries: ["函数单调性 定义", "单调性 判定"] })).toBe(
      "「函数单调性 定义」 等 2 组查询",
    );
    expect(studyToolIntent("research_knowledge_point", { knowledge_point: "复合函数单调性" })).toBe("复合函数单调性");
    expect(studyToolIntent("split_knowledge_points", { topic: "函数单调性", subject: "高中数学" })).toBe(
      "主题：函数单调性 · 学科：高中数学",
    );
    expect(studyToolIntent("web_search_knowledge", undefined)).toBeUndefined();
  });
});

describe("tool-adapters：结果摘要", () => {
  it("按工具语义生成一行摘要", () => {
    expect(summarizeStudyToolResult("split_knowledge_points", { knowledge_points: [1, 2, 3] })).toBe("拆出 3 个知识点");
    expect(summarizeStudyToolResult("web_search_knowledge", { results: [1, 2] })).toBe("获取 2 个来源");
    expect(summarizeStudyToolResult("search_questions_by_knowledge", { questions: [1] })).toBe("匹配 1 道题");
    expect(summarizeStudyToolResult("generate_study_material", { markdown: "abc" })).toBe("成稿约 3 字");
    expect(summarizeStudyToolResult("export_study_markdown", { md_url: "/x.md" })).toBe("已生成下载链接");
    expect(summarizeStudyToolResult("unknown", {})).toBe("执行完成");
  });
});

describe("tool-adapters：来源提取", () => {
  it("从检索结果中提取 title/url/snippet", () => {
    const sources = extractStudySources("web_search_knowledge", {
      results: [
        { title: "单调函数 · 百度百科", url: "https://baike.example/1", snippet: "单调函数是指…" },
        { title: "无 URL 条目" },
        { name: "知乎回答", link: "https://zhihu.example/2", summary: "同增异减…" },
      ],
    });
    expect(sources).toHaveLength(2);
    expect(sources[0]).toMatchObject({ title: "单调函数 · 百度百科", url: "https://baike.example/1" });
    expect(sources[1]).toMatchObject({ title: "知乎回答", url: "https://zhihu.example/2" });
  });

  it("非检索工具或空结果返回空数组", () => {
    expect(extractStudySources("generate_study_material", { markdown: "x" })).toEqual([]);
    expect(extractStudySources("web_search_knowledge", {})).toEqual([]);
    expect(extractStudySources("web_search_knowledge", undefined)).toEqual([]);
  });
});
