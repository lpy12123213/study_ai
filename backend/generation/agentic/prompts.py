from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from backend.generation.agentic.prompt_contracts import JsonOutputContract, MarkdownOutputContract

JSON_ONLY_GUARDRAIL = "Output a strict JSON object only. Do not output Markdown or extra explanation."
NO_MARKDOWN_FENCE_GUARDRAIL = "Do not wrap the result in a code fence and do not use ```."
NO_HIDDEN_COT_GUARDRAIL = "Give only concise reasons or evidence. Do not reveal hidden chain-of-thought."
LANGUAGE_MATCH_GUARDRAIL = (
    "For all user-facing natural-language content, match the language of the user's latest request unless the "
    "user explicitly asks for another language. Keep machine-readable field names, IDs, enum values, and code "
    "identifiers unchanged."
)
SOURCE_GROUNDING_GUARDRAIL = (
    "Synthesize only from the provided sources and materials. Do not fabricate sources; when information is "
    "insufficient, mark the statement as an inference."
)
ORIGINAL_REWRITE_GUARDRAIL = (
    "All explanations must be original rewrites in your own words. Do not copy source text verbatim."
)
EDU_MATH_FORMAT_GUARDRAIL = (
    "Use LaTeX for mathematical formulas: inline \\(...\\), display \\[...\\]. Use Markdown tables or "
    "array/matrix/cases when appropriate."
)
NO_URL_IN_MARKDOWN_GUARDRAIL = "The final Markdown must not include URLs, external links, or a references section."


PROMPT_INVENTORY_TARGETS: Tuple[str, ...] = (
    "backend/agent/core.py",
    "backend/agent/react/prompts.py",
    "backend/agent/planning/planner.py",
    "backend/agent/reflector.py",
    "backend/agent/executor.py",
    "backend/agent/tools/search/deep_research.py",
    "backend/agent/tools/search/web_search_knowledge_impl.py",
    "backend/agent/tools/analysis/source_synthesis.py",
    "backend/agent/tools/analysis/self_critique.py",
    "backend/agent/tools/analysis/content_review.py",
    "backend/agent/tools/analysis/refine_draft.py",
    "backend/agent/tools/knowledge/knowledge_points.py",
    "backend/agent/tools/knowledge/study_material_generation.py",
    "backend/agent/tools/generation/diagram_planning.py",
    "backend/agent/tools/generation/latex_export_convert.py",
    "backend/agent/tools/generation/latex_export_refine.py",
    "backend/generation/question_library/brainstorm.py",
    "backend/generation/question_library/draft_realization.py",
    "backend/generation/question_library/generation.py",
    "backend/generation/question_library/judging.py",
    "backend/api/question_evaluate.py",
    "backend/generation/lesson_plan/prompts.py",
    "backend/generation/lesson_plan/planning.py",
    "backend/generation/lesson_plan/writing.py",
    "backend/generation/lesson_plan/export.py",
    "backend/generation/deepthink/prompts.py",
    "backend/workspace/chat/prompts.py",
    "backend/generation/knowledge_video/llm.py",
    "backend/integrations/mcp/tools/stdio_handlers.py",
    "backend/integrations/mcp/tools/reviewer.py",
)


class _PromptInventoryAllowlist:
    """Temporary migration allowlist for inline prompt locations.

    The initial inventory is intentionally broad so existing inline prompts are
    visible without breaking the branch. As prompts move into PromptRegistry,
    this allowlist should shrink to explicit file:line entries and eventually
    to an empty set.
    """

    def __contains__(self, item: object) -> bool:
        rel = str(item or "").split(":", 1)[0].replace("\\", "/")
        return rel in PROMPT_INVENTORY_TARGETS


PROMPT_INVENTORY_ALLOWLIST = _PromptInventoryAllowlist()


@dataclass(frozen=True)
class PromptRenderResult:
    prompt_id: str
    role: str
    version: str
    content: str
    output_contract: object
    content_hash: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    role: str
    version: str
    input_keys: Sequence[str]
    output_contract: object
    template: str
    tags: Sequence[str] = field(default_factory=tuple)
    description: str = ""

    def __post_init__(self) -> None:
        if not str(self.id or "").strip():
            raise ValueError("missing_prompt_id")
        if not str(self.role or "").strip():
            raise ValueError("missing_prompt_role")
        if not str(self.version or "").strip():
            raise ValueError("missing_prompt_version")
        if not str(self.template or "").strip():
            raise ValueError("missing_prompt_template")

    def render(self, values: Mapping[str, object]) -> PromptRenderResult:
        data = dict(values or {})
        missing = [key for key in self.input_keys if key not in data]
        if missing:
            raise KeyError(f"missing_prompt_inputs: {','.join(missing)}")
        try:
            content = self.template.format(**data)
        except KeyError:
            raise
        except Exception as exc:
            raise ValueError(f"prompt_render_failed: {self.id}: {exc}") from exc
        return PromptRenderResult(
            prompt_id=self.id,
            role=self.role,
            version=self.version,
            content=content,
            output_contract=self.output_contract,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            metadata={"tags": list(self.tags), "description": self.description},
        )


class PromptRegistry:
    def __init__(self, templates: Iterable[PromptTemplate] | None = None) -> None:
        self._templates: Dict[str, PromptTemplate] = {}
        for template in templates or ():
            self.register(template)

    def register(self, template: PromptTemplate) -> None:
        prompt_id = str(template.id or "").strip()
        if not prompt_id:
            raise ValueError("missing_prompt_id")
        if prompt_id in self._templates:
            raise ValueError(f"duplicate_prompt_id: {prompt_id}")
        self._templates[prompt_id] = template

    def get(self, prompt_id: str) -> PromptTemplate:
        pid = str(prompt_id or "").strip()
        if pid not in self._templates:
            raise KeyError(f"prompt_not_found: {pid}")
        return self._templates[pid]

    def render(self, prompt_id: str, **values: object) -> PromptRenderResult:
        return self.get(prompt_id).render(values)

    def list_templates(self) -> List[PromptTemplate]:
        return list(self._templates.values())


def _json_template(*, prompt_id: str, role: str, input_keys: Sequence[str], body: str) -> PromptTemplate:
    return PromptTemplate(
        id=prompt_id,
        role=role,
        version="v1",
        input_keys=tuple(input_keys),
        output_contract=JsonOutputContract(),
        template="\n".join(
            [
                body.strip(),
                LANGUAGE_MATCH_GUARDRAIL,
                JSON_ONLY_GUARDRAIL,
                NO_MARKDOWN_FENCE_GUARDRAIL,
                NO_HIDDEN_COT_GUARDRAIL,
            ]
        ),
    )


def _markdown_template(
    *,
    prompt_id: str,
    role: str,
    input_keys: Sequence[str],
    body: str,
    educational_writing: bool = False,
) -> PromptTemplate:
    guardrails = [body.strip(), LANGUAGE_MATCH_GUARDRAIL]
    if educational_writing:
        guardrails.extend(
            [
                ORIGINAL_REWRITE_GUARDRAIL,
                SOURCE_GROUNDING_GUARDRAIL,
                EDU_MATH_FORMAT_GUARDRAIL,
                NO_URL_IN_MARKDOWN_GUARDRAIL,
            ]
        )
    guardrails.append(NO_HIDDEN_COT_GUARDRAIL)
    return PromptTemplate(
        id=prompt_id,
        role=role,
        version="v1",
        input_keys=tuple(input_keys),
        output_contract=MarkdownOutputContract(educational_writing=educational_writing),
        template="\n".join(guardrails),
    )


def create_default_prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    for template in (
        _json_template(
            prompt_id="agent.react.controller.v1",
            role="system",
            input_keys=(),
            body=(
                "You are a tool-driven study-material generation agent (ReAct). Complete retrieval, aggregation, "
                "writing, review, and export through multiple tool calls.\n"
                "Choose exactly one next action per turn, or finish when the evidence and artifact are sufficient.\n"
                "\n"
                "Splitting knowledge points: you decide whether to split the topic. "
                "Use it when the topic is broad/composite (multiple sub-concepts). Skip it for tightly-focused "
                "single-concept topics. Never re-split if working memory already has split_knowledge_points.\n"
                "PREFER inline splitting via the special action `set_knowledge_points`: directly emit the list in "
                "arguments.knowledge_points (3-8 items, each 2-12 chars). This writes the split to working memory "
                "WITHOUT spending a tool/LLM round-trip. "
                "Example arguments shape: knowledge_points is an array of short strings. "
                "Only call the split_knowledge_points tool when you are uncertain and want a dedicated LLM pass to do "
                "split + review.\n"
                "\n"
                "Research depth policy (per study_options.preset):\n"
                "- quick: cover key definitions only, 2-3 tool kinds is enough.\n"
                "- standard: each KP gets at least one web_search_knowledge plus one wikipedia/mediawiki call.\n"
                "- deep: each KP gets at least 2 source kinds; switch tools or query_hints when Quality<HIGH.\n"
                "- research: each KP MUST cover at least 3 source kinds (web_search + wikipedia/mediawiki + "
                "stackexchange/github_search or browse_web_pages). Run an additional retrieval round when Quality<HIGH. "
                "Do NOT finish after only one or two retrievals.\n"
                "\n"
                "Quality policy: cover every knowledge point first. If a tool result is LOW or FAILED, change the "
                "query, switch tools, or move to another knowledge point instead of repeating ineffective calls.\n"
                "\n"
                "Finish criteria (all must hold):\n"
                "1) generate_study_material covers every KP (or topic needs no split).\n"
                "2) assemble_study_archive produced complete Markdown.\n"
                "3) review_content passed=true (or budget exhausted with no recovery option).\n"
                "4) Research depth meets the preset minimum above.\n"
                "Do not finish early just because one or two retrievals returned MEDIUM quality - in research mode "
                "explicitly avoid this.\n"
                "\n"
                "Budget policy: tool calls and LLM decisions are limited. When the budget is tight, prioritize "
                "assemble/save/export/review and close the run. In research mode, prefer one more retrieval round "
                "over premature finishing as long as budget remains.\n"
                "\n"
                "batch_mode may be per_knowledge_point to run the same tool for all knowledge points in parallel.\n"
                "Output fields: thought, action, batch_mode, arguments, note."
            ),
        ),
        _json_template(
            prompt_id="agent.planner.study_materials.v1",
            role="system",
            input_keys=("topic", "subject", "allowed_tools", "search_policy"),
            body=(
                "You are the planner for a self-study material generation system. Produce an executable plan.\n"
                "Topic: {topic}\nSubject: {subject}\nAllowed tools: {allowed_tools}\nSearch policy: {search_policy}\n"
                "Use the smallest sufficient tool chain that preserves the requested quality and performance.\n"
                "Output fields: rationale, steps."
            ),
        ),
        _markdown_template(
            prompt_id="study.material.writer.v1",
            role="system",
            input_keys=("knowledge_point", "subject", "source_brief"),
            educational_writing=True,
            body=(
                "You are a rigorous teacher writing self-study material. Output Markdown.\n"
                "Subject: {subject}\nKnowledge point: {knowledge_point}\nSource brief: {source_brief}"
            ),
        ),
        _json_template(
            prompt_id="study.material.document_review.v1",
            role="system",
            input_keys=("topic", "markdown"),
            body=(
                "You are a rigorous educational manuscript reviewer. Check whether the Markdown is accurate, "
                "clear, and suitable for self-study.\n"
                "Topic: {topic}\nMarkdown: {markdown}\n"
                "Output fields: passed, issues, suggestions."
            ),
        ),
        _json_template(
            prompt_id="deepthink.generator.v1",
            role="system",
            input_keys=("subject",),
            body=(
                "You are an expert problem solver in {subject} participating in tree-of-thought search.\n"
                "Given the current solving state, propose multiple distinct next reasoning actions.\n"
                "Output next actions, not the full solution. Each candidate must be concrete and executable.\n"
                "Fields: thought, reasoning, is_final."
            ),
        ),
        _json_template(
            prompt_id="deepthink.evaluator.v1",
            role="system",
            input_keys=("subject",),
            body=(
                "You are a rigorous {subject} reviewer scoring next reasoning actions for tree pruning.\n"
                "Evaluate correctness, progress, and feasibility.\n"
                "score must be 0-10. reasoning must contain only 1-3 concise scoring reasons.\n"
                "Fields: score, reasoning, issues."
            ),
        ),
        _markdown_template(
            prompt_id="deepthink.synthesizer.v1",
            role="system",
            input_keys=("subject",),
            body=(
                "You are an expert {subject} teacher. Based on the best reasoning path, write a complete "
                "student-facing solution.\n"
                "Output plain Markdown. Formulas are allowed. Prefer problem analysis, solution steps, and the "
                "final answer."
            ),
        ),
        _json_template(
            prompt_id="lesson_plan.writer.v1",
            role="system",
            input_keys=(),
            body=(
                "You are a senior educational content designer specializing in lesson plans.\n"
                "Rewrite all content in your own words. Do not copy any source text verbatim.\n"
                "The lesson plan must be clear, practical, and student-centered.\n"
                "Output fields: title, objectives, sections, summary. Each sections item must contain title, "
                "duration_minutes, content, activities, resources."
            ),
        ),
        PromptTemplate(
            id="chat.paper_compose.system.v1",
            role="system",
            version="v1",
            input_keys=("subject", "subject_topic", "plan_open", "plan_close"),
            output_contract=MarkdownOutputContract(),
            template=(
                "You are Smart Paper Composer. Your goal is to search the question bank according to the user's "
                "requirements, then create and save a paper only after the user confirms.\n"
                "Current subject: {subject}\n\n"
                "Language policy\n"
                "- Match the language of the user's latest message for all user-facing prose unless the user "
                "explicitly requests another language.\n"
                "- Keep tool names, JSON field names, IDs, and supported Chinese enum values unchanged.\n\n"
                "Compliance and copyright requirements\n"
                "- Do not output full question stems, options, answers, or analyses. Output only question IDs and "
                "necessary metadata such as type, difficulty, knowledge points, and source links.\n"
                "- If the user asks for the original text, tell them to view it on the question-bank page and "
                "provide the link when available.\n\n"
                "Difficulty convention\n"
                "- A lower difficulty coefficient means a harder question: hard < medium < easy.\n"
                "- Tool enum values for difficulty may remain Chinese, for example: 困难, 中等, 简单.\n\n"
                "Tool discipline\n"
                "- Use the smallest sufficient set of tool calls. Do not inspect full question details unless "
                "needed for filtering, deduplication, or final assembly.\n"
                "- Prefer get_available_filters only when the request depends on grade, textbook, province, "
                "paper type, or other filter options.\n"
                "- Prefer compose_paper_blueprint for confirmed paper assembly. Use search_questions for small "
                "probing searches during planning.\n\n"
                "Two-phase workflow\n"
                "Phase A, planning: when needed, call get_available_filters first, then run 1-3 small "
                "search_questions probes with limit=5-8. Then output a blueprint JSON wrapped exactly in tags:\n"
                "{plan_open}\n"
                '{{"version":1,"subject":"{subject}","paper_name":"Suggested paper name","blueprint":[{{"keyword":"{subject_topic}","count":10,"difficulty":"中等","question_type":"单选题"}}]}}\n'
                "{plan_close}\n"
                "Outside the tags, use only 1-3 sentences to ask the user to confirm execution.\n\n"
                "Phase B, execution: after user confirmation, prefer compose_paper_blueprint to assemble question "
                "IDs. Use batch_get_question_details only when metadata is necessary. Finally call create_paper "
                "and return the paper_id.\n"
                + NO_HIDDEN_COT_GUARDRAIL
            ),
        ),
    ):
        registry.register(template)

    json_specs = [
        (
            "agent.reflector.study_materials.v1",
            "You are a rigorous self-study material reviewer. Check structure, coverage, factual consistency, "
            "source constraints, and self-study usability. Output fields: passed, issues, suggestions.",
        ),
        (
            "study.kp.split.v1",
            "You are an instructional structure assistant. Split the topic into a knowledge-point tree suitable "
            "for self-study. The granularity must be teachable, verifiable, and orderable. Output fields: "
            "knowledge_points, rationale.",
        ),
        (
            "study.kp.review.v1",
            "You are a knowledge-point review assistant. Check whether the split is too broad, too narrow, "
            "duplicated, or missing prerequisites. Output fields: passed, issues, knowledge_points.",
        ),
        (
            "study.sources.synthesize.v1",
            "You are a source synthesis assistant. Denoise search results and page excerpts into a source brief. "
            "Do not copy the original text. Distinguish facts, inferences, and uncertain information. Output "
            "fields: brief, facts, gaps.",
        ),
        (
            "study.material.outline.v1",
            "You are an instructional outline assistant. Generate a writing outline and acceptance checks for a "
            "single knowledge point. Output fields: sections, prerequisites, verify.",
        ),
        (
            "study.material.section_reviewer.v1",
            "You are a knowledge-section reviewer agent. Check whether the section is accurate, clear, and covers "
            "conditions, misconceptions, and applications. Output fields: passed, issues, suggestions.",
        ),
        (
            "search.query.decompose.v1",
            "You are a research search-planning assistant. Decompose the learning topic into search questions "
            "about definitions, boundaries, proofs, applications, and misconceptions. Output fields: queries.",
        ),
        (
            "search.deep_research.learning_extraction.v1",
            "You are a research-material extraction assistant. Extract learnable facts, conditions, "
            "counterexamples, and applications from search results. Do not fabricate sources. Output fields: "
            "learnings, gaps.",
        ),
        (
            "search.source_fact.normalize.v1",
            "You are a source-fact normalization assistant. Summarize source text into short facts and mark "
            "confidence. Output fields: facts.",
        ),
        (
            "question.brainstorm.v1",
            "You are a senior curriculum researcher. Produce diverse question-writing ideas for the given topic "
            "across different ability levels. Output fields: seeds.",
        ),
        (
            "question.draft.realize.v1",
            "You are a curriculum researcher who writes, solves, and reviews questions. Generate one question "
            "with sufficient conditions, a unique answer, and verifiable analysis. Output fields: stem, answer, "
            "analysis, metadata.",
        ),
        (
            "question.draft.retry_json.v1",
            "You are a JSON repair assistant. Repair the previous truncated or malformed question JSON without "
            "changing its meaning. Output fields: stem, answer, analysis, metadata.",
        ),
        (
            "question.solve.independent.v1",
            "You are an independent solver. Solve the problem independently before considering any candidate "
            "answer, then provide the conclusion. Output fields: answer, reasoning_summary, issues.",
        ),
        (
            "question.judge.ambiguity.v1",
            "You are a question-review expert. Detect insufficient conditions, non-unique answers, ambiguous "
            "wording, and conflicting statements. Output fields: ambiguous, issues.",
        ),
        (
            "question.judge.quality.v1",
            "You are a senior curriculum researcher. Review question quality, difficulty fit, and analysis rigor "
            "against exam-evaluation standards. Output fields: score, verdict, issues.",
        ),
        (
            "question.repair.minimal.v1",
            "You are a minimal question-repair assistant. Modify only the stem, answer, or analysis needed to "
            "address the issues while preserving the original assessment goal. Output fields: patch, "
            "fixed_question.",
        ),
        (
            "question.section.regenerate.v1",
            "You are a localized rewrite assistant. Rewrite only the specified section while keeping all other "
            "fields compatible. Output fields: section_key, content.",
        ),
        (
            "question.evaluate.external.v1",
            "You are a question-quality evaluator. Review the user-provided question, answer, and analysis. "
            "Output fields: overall_score, verdict, dimensions, summary.",
        ),
        (
            "lesson_plan.kp_facts.v1",
            "You are a rigorous subject teacher. Generate factual points needed for instructional design. Output "
            "fields: definition, key_points, prerequisites, common_mistakes, methods.",
        ),
        (
            "lesson_plan.activity_planner.v1",
            "You are a senior curriculum researcher. Plan classroom activities, timing, and learning objectives. "
            "Output fields: objectives, activities, assessment.",
        ),
        (
            "knowledge_video.manim_package.v1",
            "You are a knowledge-video script assistant. Output a renderable, constrained, and safe Manim package "
            "description. Output fields: script, assets, narration, safety_notes.",
        ),
        (
            "mcp.knowledge_facts.v1",
            "You are a rigorous subject teacher. Generate factual knowledge-point notes for MCP tools. Output "
            "fields: definition, key_points, prerequisites, common_mistakes, methods.",
        ),
        (
            "mcp.review_study_material.v1",
            "You are a rigorous reviewer. Check self-study Markdown for logic, errors, and improvement points. "
            "Output fields: passed, issues, suggestions.",
        ),
    ]

    markdown_specs = [
        (
            "agent.markdown.continuation.v1",
            False,
            "You are a Markdown continuation assistant. Continue only from the end of the existing text and do "
            "not repeat prior content. Output Markdown.",
        ),
        (
            "agent.subagent.summary.v1",
            False,
            "You are an instructional summarizer. Use plain text or concise Markdown to summarize the core "
            "definition, key conclusions, and misconceptions of a knowledge point.",
        ),
        (
            "study.material.section_revision.v1",
            True,
            "You are a Markdown revision agent. Revise only the specified knowledge-point section and output the "
            "complete revised Markdown.",
        ),
        (
            "study.material.document_revision.v1",
            True,
            "You are a professional academic content editor. Precisely revise the complete self-study Markdown "
            "according to the review issues.",
        ),
        (
            "lesson_plan.latex_convert.v1",
            False,
            "You are a typesetting assistant. Convert lesson plans or study materials into LaTeX-friendly "
            "Markdown/LaTeX fragments.",
        ),
        (
            "lesson_plan.latex_repair.v1",
            False,
            "You are a LaTeX repair assistant. Make the smallest necessary corrections to the LaTeX document "
            "based on compilation errors.",
        ),
        (
            "mcp.study_section.v1",
            True,
            "You are a self-study material teacher. Generate a knowledge-point explanation section in Markdown "
            "for MCP tools.",
        ),
        (
            "mcp.solve_stepwise.v1",
            True,
            "You are a problem-solving teacher. Write a student-facing step-by-step Markdown solution.",
        ),
        (
            "mcp.context_summarize.v1",
            False,
            "You are a context compressor. Compress conversations or tool logs into a concise summary while "
            "preserving goals, constraints, decisions, and errors.",
        ),
        (
            "mcp.question_reviewer.v1",
            False,
            (
                "You are an education expert and question reviewer. Review question quality, difficulty, answer, "
                "and analysis around the user's concerns.\n"
                "Review dimensions: clarity, accuracy, difficulty fit, educational value, answer quality, and "
                "analysis quality.\n"
                "The output should include overall score, clarity score, accuracy score, strengths, weaknesses, "
                "suggestions, and verdict."
            ),
        ),
        (
            "mcp.paper_reviewer.v1",
            False,
            (
                "You are a paper reviewer. Review paper structure, question-type distribution, difficulty, "
                "coverage, and the user's special requirements.\n"
                "Prioritize the user's special requirements while independently judging correctness, difficulty, "
                "duplicate questions, out-of-scope risks, and knowledge-point coverage.\n"
                "Ignore technical display issues such as image placeholders or broken formula rendering; focus on "
                "readable text and metadata."
            ),
        ),
    ]

    for prompt_id, body in json_specs:
        registry.register(_json_template(prompt_id=prompt_id, role="system", input_keys=(), body=body))
    for prompt_id, educational_writing, body in markdown_specs:
        registry.register(
            _markdown_template(
                prompt_id=prompt_id,
                role="system",
                input_keys=(),
                body=body,
                educational_writing=educational_writing,
            )
        )
    return registry


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]
