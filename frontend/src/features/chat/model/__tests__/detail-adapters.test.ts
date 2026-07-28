import { describe, expect, it } from "vitest";

import { adaptToolDetail, adaptToolSources, formatToolArguments } from "../tool-detail-adapters";

describe("formatToolArguments", () => {
  it("隐藏空字段并保留有效值", () => {
    expect(
      formatToolArguments({
        keyword: "数列",
        limit: 5,
        edu_level: "",
        province: undefined,
        tags: [],
        opts: {},
        exclude_elective: false,
      }),
    ).toEqual([
      { key: "keyword", value: "数列" },
      { key: "limit", value: "5" },
      { key: "exclude_elective", value: "false" },
    ]);
  });

  it("对象/数组值序列化为 JSON", () => {
    expect(formatToolArguments({ x_range: [0, 6] })).toEqual([{ key: "x_range", value: "[0,6]" }]);
  });

  it("非对象输入返回空数组", () => {
    expect(formatToolArguments("raw")).toEqual([]);
    expect(formatToolArguments(undefined)).toEqual([]);
  });
});

describe("adaptToolDetail", () => {
  it("search_questions → 题目列表与筛选条件", () => {
    const detail = adaptToolDetail(
      "search_questions",
      {
        success: true,
        keyword: "数列综合",
        count: 1,
        questions: [
          { question_id: "q-1", stem: "已知等差数列…", difficulty: "中等", knowledge: ["等差数列"] },
          { malformed: true },
        ],
      },
      { keyword: "数列综合", difficulty: "中等", limit: 5 },
    );
    expect(detail.kind).toBe("questions");
    if (detail.kind !== "questions") return;
    expect(detail.count).toBe(1);
    expect(detail.items).toHaveLength(1);
    expect(detail.items[0]).toMatchObject({ id: "q-1", difficulty: "中等", knowledge: ["等差数列"] });
    // limit 不属于业务筛选条件
    expect(detail.appliedFilters.map((f) => f.key)).toEqual(["keyword", "difficulty"]);
  });

  it("python_scientific_compute → 结构化计算结果", () => {
    const detail = adaptToolDetail(
      "python_scientific_compute",
      { success: true, result_repr: "[2, 3]", result_type: "list", stdout: "", warnings: [" SymPy 警告 "], },
      { code: "result=1+1", purpose: "解方程" },
    );
    expect(detail).toMatchObject({
      kind: "compute",
      resultRepr: "[2, 3]",
      resultType: "list",
      purpose: "解方程",
      code: "result=1+1",
    });
    if (detail.kind === "compute") expect(detail.warnings).toEqual([" SymPy 警告 "]);
  });

  it("plot_function → 图像与文件信息", () => {
    const detail = adaptToolDetail("plot_function", {
      success: true,
      url: "/api/media/generated/plot.png",
      filename: "plot.png",
      cached: true,
      bytes: 38210,
    });
    expect(detail).toEqual({ kind: "plot", url: "/api/media/generated/plot.png", filename: "plot.png", cached: true, bytes: 38210 });
  });

  it("web_search → 主题摘要与链接列表", () => {
    const detail = adaptToolDetail("web_search", {
      success: true,
      query: "q",
      provider: "tavily",
      answer: "摘要",
      results: [
        { title: "甲", url: "https://a.example", snippet: "s1", published_date: "2025-01-01" },
        { url: "https://b.example" },
        "garbage",
      ],
    });
    expect(detail.kind).toBe("web");
    if (detail.kind !== "web") return;
    expect(detail.answer).toBe("摘要");
    expect(detail.results).toHaveLength(2);
    expect(detail.results[1].title).toBe("https://b.example");
  });

  it("create_paper / get_papers / 未知工具", () => {
    expect(adaptToolDetail("create_paper", { success: true, paper_id: 208, message: "试卷创建成功，ID: 208" })).toEqual({
      kind: "paper",
      paperId: 208,
      message: "试卷创建成功，ID: 208",
    });
    const papers = adaptToolDetail("get_papers", { success: true, count: 1, papers: [{ id: 3, title: "期中卷" }] });
    expect(papers).toEqual({ kind: "papers", count: 1, papers: [{ key: "3", value: "期中卷" }] });
    expect(adaptToolDetail("get_available_filters", { success: true }).kind).toBe("generic");
    expect(adaptToolDetail("search_questions", "not-an-object").kind).toBe("generic");
  });
});

describe("adaptToolSources", () => {
  it("web_search → Web 来源（仅含带链接条目）", () => {
    const sources = adaptToolSources("web_search", {
      success: true,
      results: [
        { title: "甲", url: "https://a.example", snippet: "s" },
        { title: "乙" },
      ],
    });
    expect(sources).toEqual([{ title: "甲", url: "https://a.example", snippet: "s", kind: "web" }]);
  });

  it("search_questions → 题库来源标识", () => {
    const sources = adaptToolSources("search_questions", {
      success: true,
      questions: [{ question_id: "q-1", difficulty: "中等", knowledge: ["等差数列"] }],
    });
    expect(sources).toEqual([
      { title: "题目 q-1（中等）", snippet: "知识点：等差数列", kind: "question-bank", url: undefined },
    ]);
  });

  it("create_paper → 试卷入口；plot_function → 生成文件", () => {
    expect(adaptToolSources("create_paper", { success: true, paper_id: 208 })).toEqual([
      { title: "试卷 ID: 208", url: "/papers/208", kind: "paper" },
    ]);
    expect(adaptToolSources("plot_function", { success: true, url: "/api/media/generated/p.png", filename: "p.png" })).toEqual([
      { title: "p.png", url: "/api/media/generated/p.png", kind: "file" },
    ]);
  });

  it("失败结果与其他工具无来源", () => {
    expect(adaptToolSources("web_search", { success: false, error: "x" })).toEqual([]);
    expect(adaptToolSources("python_scientific_compute", { success: true, result_repr: "1" })).toEqual([]);
  });
});
