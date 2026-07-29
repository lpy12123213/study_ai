import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StemHtml } from "@/components/question/stem-html";

describe("StemHtml", () => {
  it("renders inline and display TeX while preserving surrounding HTML", () => {
    const { container } = render(
      <StemHtml html={"<p>已知 \\(f(x)=x^2\\)，且 $a+b=3$。</p><div>\\[x=1\\]</div>"} />,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(3);
    expect(container.querySelector(".katex-display")).not.toBeNull();
    expect(container.querySelector("p")).toHaveTextContent("已知");
  });

  it("keeps code samples literal and renders formulas outside code", () => {
    const { container } = render(<StemHtml html={"<code>$x^2$</code><span>$y^2$</span>"} />);

    expect(container.querySelector("code")).toHaveTextContent("$x^2$");
    expect(container.querySelector("code .katex")).toBeNull();
    expect(container.querySelector("span .katex")).not.toBeNull();
  });

  it("keeps malformed TeX visible instead of throwing", () => {
    const { container } = render(<StemHtml html={"答案为 \\(\\frac{1}\\)。"} />);

    expect(container.firstElementChild).toHaveTextContent("答案为");
    expect(container.querySelector(".katex-error")).not.toBeNull();
  });

  it("continues to proxy remote images", () => {
    const source = "https://example.com/question.png";
    const { container } = render(<StemHtml html={`<img src="${source}" alt="题图">`} />);
    const image = container.querySelector("img");

    expect(image).toHaveAttribute("src", `/api/media/proxy?url=${encodeURIComponent(source)}`);
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
  });
});
