import { describe, expect, it } from "vitest";

import { parseGaokaoImportText, preflightGaokaoImport } from "../gaokao-import";

describe("高考真题导入预检", () => {
  it("接受数组或 items 包装，并保留 LaTeX 与原位图片 HTML", () => {
    const candidates = parseGaokaoImportText(JSON.stringify({
      items: [
        {
          question_id: "gk-1",
          subject: "高中数学",
          stem: '<p>函数 \\(f(x)=x^2\\)</p><img src="/api/media/generated/q.svg">',
          source: { exam_year: 2024, region: "全国", paper_name: "新课标I卷", question_number: "3" },
        },
      ],
    }));
    const result = preflightGaokaoImport(candidates);

    expect(result.issues).toEqual([]);
    expect(result.validItems[0].stem).toContain("\\(f(x)=x^2\\)");
    expect(result.validItems[0].stem).toContain("<img");
  });

  it("拒绝重复 question_id、越界年份和缺失结构化出处", () => {
    const result = preflightGaokaoImport([
      { question_id: "same", subject: "物理", stem: "题干", source: { exam_year: 2024, region: "全国", paper_name: "甲卷" } },
      { question_id: "same", subject: "物理", stem: "题干", source: { exam_year: 2201, region: "", paper_name: "" } },
    ]);

    expect(result.validItems).toHaveLength(1);
    expect(result.issues.map((issue) => issue.field)).toEqual(
      expect.arrayContaining(["question_id", "source.exam_year", "source.region", "source.paper_name"]),
    );
  });
});
