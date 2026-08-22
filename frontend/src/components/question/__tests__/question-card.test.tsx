import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { QuestionCard } from "@/components/question/question-card";

function ExpandableQuestion() {
  const [expanded, setExpanded] = useState(false);
  return (
    <QuestionCard
      question={{
        question_id: "gk-1",
        stem: '<p>题干含公式 \\(f(x)=x^2\\)</p><img src="https://example.com/figure.png" alt="题图">',
        answer: "答案为 \\(x=1\\)",
        analysis: "由 \\(x^2=1\\) 可得。",
        has_answer: true,
        has_analysis: true,
      }}
      expanded={expanded}
      onExpandedChange={setExpanded}
    />
  );
}

describe("QuestionCard", () => {
  it("在题目原位置渲染 LaTeX 和图片，点击题干后原位展开答案解析", () => {
    const { container } = render(<ExpandableQuestion />);

    const stem = screen.getByText("题干含公式", { exact: false });
    const image = screen.getByAltText("题图");
    expect(stem.querySelector(".katex")).not.toBeNull();
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
    expect(screen.queryByText("答案为", { exact: false })).not.toBeInTheDocument();

    fireEvent.click(stem);

    expect(screen.getByText("答案为", { exact: false }).querySelector(".katex")).not.toBeNull();
    expect(screen.getByText("由", { exact: false }).querySelector(".katex")).not.toBeNull();
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });
});
