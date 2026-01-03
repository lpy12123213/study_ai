import { BaseBoxShapeUtil, HTMLContainer, T } from "tldraw";
import type { TLBaseShape } from "@tldraw/tlschema";

export type QuestionCardShape = TLBaseShape<
  "question-card",
  {
    w: number;
    h: number;
    questionId: string;
    title: string;
    meta: string;
    html: string;
  }
>;

export class QuestionCardShapeUtil extends BaseBoxShapeUtil<QuestionCardShape> {
  static override type = "question-card" as const;

  static override props = {
    w: T.number,
    h: T.number,
    questionId: T.string,
    title: T.string,
    meta: T.string,
    html: T.string,
  };

  getDefaultProps(): QuestionCardShape["props"] {
    return {
      w: 520,
      h: 320,
      questionId: "",
      title: "",
      meta: "",
      html: "",
    };
  }

  component(shape: QuestionCardShape) {
    return (
      <HTMLContainer className="epa-question-card">
        <div className="epa-question-card__inner">
          <div className="epa-question-card__header">
            <div className="epa-question-card__title">
              {shape.props.title || (shape.props.questionId ? `题目 ${shape.props.questionId}` : "题目")}
            </div>
            {shape.props.meta ? (
              <div className="epa-question-card__meta">{shape.props.meta}</div>
            ) : null}
          </div>
          <div
            className="epa-question-card__body"
            dangerouslySetInnerHTML={{ __html: shape.props.html || "" }}
          />
        </div>
      </HTMLContainer>
    );
  }

  indicator(shape: QuestionCardShape) {
    return <rect width={shape.props.w} height={shape.props.h} />;
  }
}

