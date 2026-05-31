// AUTO-GENERATED. Do not edit by hand.
// Paths for the `generation` domain.
// Regenerate via `npm run gen:api`.

import type { components, operations } from './components'

export type { components, operations }

export interface paths {
    "/api/deepthink": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Deepthink Endpoint
         * @description DeepThink SSE endpoint (POST + streaming response body).
         *
         *     NOTE:
         *     - `/api/tasks` is the canonical long-task API.
         *     - This endpoint is kept as a thin compatibility wrapper for older clients.
         */
        post: operations["deepthink_endpoint_api_deepthink_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/essay-evaluations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List History */
        get: operations["list_history_api_essay_evaluations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/essay-evaluations/evaluate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Evaluate
         * @description One-shot synchronous evaluation that also persists the result.
         *
         *     Returns ``{"evaluation_id": int, "result": EssayEvaluationResult}``.
         *     Use ``POST /api/tasks/essay-evaluations/evaluate`` for streaming progress.
         */
        post: operations["evaluate_api_essay_evaluations_evaluate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/essay-evaluations/{evaluation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Detail */
        get: operations["get_detail_api_essay_evaluations__evaluation_id__get"];
        put?: never;
        post?: never;
        /** Delete */
        delete: operations["delete_api_essay_evaluations__evaluation_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/lesson-plans": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Plans
         * @description List all lesson plans owned by the current user.
         */
        get: operations["list_plans_api_lesson_plans_get"];
        put?: never;
        /**
         * Create Plan
         * @description Create a new lesson plan.
         */
        post: operations["create_plan_api_lesson_plans_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/lesson-plans/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Export Plan
         * @description Export a lesson plan to various formats (owner-scoped).
         */
        post: operations["export_plan_api_lesson_plans_export_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/lesson-plans/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate Plan
         * @description Generate a lesson plan using AI with streaming response.
         *
         *     NOTE:
         *     - `/api/tasks` is the canonical long-task API.
         *     - This endpoint is kept as a thin compatibility wrapper for older clients.
         */
        post: operations["generate_plan_api_lesson_plans_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/lesson-plans/{plan_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Plan
         * @description Get a specific lesson plan owned by the current user.
         */
        get: operations["get_plan_api_lesson_plans__plan_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Plan
         * @description Delete a lesson plan owned by the current user.
         */
        delete: operations["delete_plan_api_lesson_plans__plan_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-evaluate/evaluate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Evaluate Questions */
        post: operations["evaluate_questions_api_question_evaluate_evaluate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-evaluate/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Search Questions */
        post: operations["search_questions_api_question_evaluate_search_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/crawl": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Crawl And Save */
        post: operations["crawl_and_save_api_question_library_crawl_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate And Save */
        post: operations["generate_and_save_api_question_library_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Items */
        get: operations["list_items_api_question_library_items_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items/bulk-delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bulk Delete Items */
        post: operations["bulk_delete_items_api_question_library_items_bulk_delete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items/{question_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Item Detail */
        get: operations["get_item_detail_api_question_library_items__question_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items/{question_id}/export-to-basket": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Export Item To Basket */
        post: operations["export_item_to_basket_api_question_library_items__question_id__export_to_basket_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items/{question_id}/hide": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Hide Item */
        post: operations["hide_item_api_question_library_items__question_id__hide_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items/{question_id}/star": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Star Item */
        post: operations["star_item_api_question_library_items__question_id__star_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items/{question_id}/unhide": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unhide Item */
        post: operations["unhide_item_api_question_library_items__question_id__unhide_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/items/{question_id}/unstar": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unstar Item */
        post: operations["unstar_item_api_question_library_items__question_id__unstar_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/previews/latest/pending": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Latest Pending Preview */
        get: operations["get_latest_pending_preview_api_question_library_previews_latest_pending_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/previews/{preview_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Preview */
        get: operations["get_preview_api_question_library_previews__preview_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/previews/{preview_id}/commit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Commit Preview */
        post: operations["commit_preview_api_question_library_previews__preview_id__commit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/previews/{preview_id}/discard": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Discard Preview */
        post: operations["discard_preview_api_question_library_previews__preview_id__discard_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/previews/{preview_id}/regenerate-section": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Regenerate Preview Section */
        post: operations["regenerate_preview_section_api_question_library_previews__preview_id__regenerate_section_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/score": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Score Question Library */
        post: operations["score_question_library_api_question_library_score_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Question Library Sessions */
        get: operations["list_question_library_sessions_api_question_library_sessions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Question Library Session */
        get: operations["get_question_library_session_api_question_library_sessions__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}/archive": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Archive Question Library Session */
        post: operations["archive_question_library_session_api_question_library_sessions__session_id__archive_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}/questions/{question_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Session Question */
        post: operations["approve_session_question_api_question_library_sessions__session_id__questions__question_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}/questions/{question_id}/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirm Session Question */
        post: operations["confirm_session_question_api_question_library_sessions__session_id__questions__question_id__confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}/questions/{question_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reject Session Question */
        post: operations["reject_session_question_api_question_library_sessions__session_id__questions__question_id__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}/questions/{question_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Review Session Question */
        post: operations["review_session_question_api_question_library_sessions__session_id__questions__question_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}/questions/{question_id}/unconfirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Unconfirm Session Question */
        post: operations["unconfirm_session_question_api_question_library_sessions__session_id__questions__question_id__unconfirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/sessions/{session_id}/stop": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Stop Question Library Session */
        post: operations["stop_question_library_session_api_question_library_sessions__session_id__stop_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Task Status */
        get: operations["get_task_status_api_question_library_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-library/tasks/{task_id}/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Stream Task */
        get: operations["stream_task_api_question_library_tasks__task_id__stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-materials/convert-markdown-to-latex": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Convert Markdown To Latex */
        post: operations["convert_markdown_to_latex_api_study_materials_convert_markdown_to_latex_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-materials/convert-markdown-to-latex/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Convert Markdown To Latex Stream */
        post: operations["convert_markdown_to_latex_stream_api_study_materials_convert_markdown_to_latex_stream_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-materials/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate Study Materials
         * @description Start a new study-materials generation task and stream events.
         */
        post: operations["generate_study_materials_api_study_materials_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-materials/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Study Materials Task */
        get: operations["get_study_materials_task_api_study_materials_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-materials/tasks/{task_id}/continue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Continue Study Materials Task
         * @description Continue a completed/failed task with one bounded improvement iteration (streams SSE events).
         */
        post: operations["continue_study_materials_task_api_study_materials_tasks__task_id__continue_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-materials/tasks/{task_id}/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Stream Study Materials Task
         * @description Resume a running/completed task and replay SSE events after `after_seq`.
         */
        get: operations["stream_study_materials_task_api_study_materials_tasks__task_id__stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
