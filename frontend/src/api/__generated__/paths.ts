// AUTO-GENERATED. Do not edit by hand.
// Merged `paths` interface mirroring the original monolithic file.

import type { components, operations } from './components'

export type { components, operations }

export interface paths {

    "/api/annotations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List User Annotations */
        get: operations["list_user_annotations_api_annotations_get"];
        put?: never;
        /** Create User Annotation */
        post: operations["create_user_annotation_api_annotations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/annotations/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export User Annotations */
        get: operations["export_user_annotations_api_annotations_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/annotations/{annotation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update User Annotation */
        patch: operations["update_user_annotation_api_annotations__annotation_id__patch"];
        trace?: never;
    };
    "/api/auth/change-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Change Password
         * @description Change current user's password.
         */
        post: operations["change_password_api_auth_change_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login
         * @description Authenticate a user and return a JWT.
         */
        post: operations["login_api_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description Revoke the current JWT (best-effort).
         */
        post: operations["logout_api_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Me
         * @description Get current user info.
         */
        get: operations["get_me_api_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/register": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Register
         * @description Register a new user (admin only).
         */
        post: operations["register_api_auth_register_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Users
         * @description List all users (admin only).
         */
        get: operations["list_users_api_auth_users_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/available-filters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Available Filters
         * @description Get available search filters for a subject (grades/textbook versions/question types/provinces, etc.).
         */
        post: operations["available_filters_api_available_filters_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/blueprints/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Blueprints */
        get: operations["get_blueprints_api_blueprints__get"];
        put?: never;
        /** Create Blueprint */
        post: operations["create_blueprint_api_blueprints__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/blueprints/{blueprint_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get One Blueprint */
        get: operations["get_one_blueprint_api_blueprints__blueprint_id__get"];
        put?: never;
        post?: never;
        /** Remove Blueprint */
        delete: operations["remove_blueprint_api_blueprints__blueprint_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/canvas/boards": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Boards */
        get: operations["list_boards_api_canvas_boards_get"];
        put?: never;
        /** Create Board */
        post: operations["create_board_api_canvas_boards_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/canvas/boards/{board_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Board */
        get: operations["get_board_api_canvas_boards__board_id__get"];
        /** Put Board */
        put: operations["put_board_api_canvas_boards__board_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/canvas/boards/{board_id}/pick-questions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Pick Questions
         * @description Use crawler + MCP sub-AI selector to pick questions, then return render-ready HTML.
         *
         *     Notes:
         *     - Formula rendering: inline SVG (no svg2latex).
         *     - Images: rewritten to `/api/media/proxy` for on-demand download + cache.
         */
        post: operations["pick_questions_api_canvas_boards__board_id__pick_questions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/canvas/boards/{board_id}/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Versions */
        get: operations["get_versions_api_canvas_boards__board_id__versions_get"];
        put?: never;
        /** Create Version */
        post: operations["create_version_api_canvas_boards__board_id__versions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/canvas/boards/{board_id}/versions/{version_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Version */
        get: operations["get_version_api_canvas_boards__board_id__versions__version_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/canvas/questions/{question_id}/render": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Render Question
         * @description Render a single question as HTML with inline SVG formulas and cached images.
         */
        get: operations["render_question_api_canvas_questions__question_id__render_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chat": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Chat Endpoint
         * @description 处理聊天请求，返回 SSE 流式响应（前端通过 fetch 读取）。
         *     支持学科选择。
         */
        post: operations["chat_endpoint_api_chat_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/compose-blueprint": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Compose Blueprint
         * @description Compose question IDs according to a multi-slot blueprint.
         */
        post: operations["compose_blueprint_api_compose_blueprint_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Runtime Config
         * @description 返回当前运行配置摘要（不包含密钥等敏感信息）。
         */
        get: operations["get_runtime_config_api_config_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/conversations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Conversations List
         * @description 获取对话列表
         */
        get: operations["get_conversations_list_api_conversations_get"];
        put?: never;
        /**
         * Create New Conversation
         * @description 创建新对话
         */
        post: operations["create_new_conversation_api_conversations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/conversations/{conv_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Remove Conversation
         * @description 删除对话
         */
        delete: operations["remove_conversation_api_conversations__conv_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Conversation
         * @description 更新对话信息（目前仅支持标题）
         */
        patch: operations["update_conversation_api_conversations__conv_id__patch"];
        trace?: never;
    };
    "/api/conversations/{conv_id}/fork": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Fork Existing Conversation
         * @description 从某条消息开始“分叉”对话，生成一个新的对话（复制父对话的消息前缀）。
         *
         *     说明：
         *     - 用于前端画布式分叉对话：分叉后的新对话可以继续独立对话。
         *     - 复制的消息为父对话中按时间排序，直到 `message_id`（包含该条消息）。
         */
        post: operations["fork_existing_conversation_api_conversations__conv_id__fork_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/conversations/{conv_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Conversation Messages
         * @description 获取对话消息
         */
        get: operations["get_conversation_messages_api_conversations__conv_id__messages_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Dashboard Csv */
        get: operations["export_dashboard_csv_api_dashboard_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/dashboard/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Dashboard Stats */
        get: operations["get_dashboard_stats_api_dashboard_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
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
    "/api/exports/files": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Files */
        get: operations["list_files_api_exports_files_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/exports/zip": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Zip Files */
        post: operations["zip_files_api_exports_zip_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List User Feedback */
        get: operations["list_user_feedback_api_feedback_get"];
        put?: never;
        /** Create User Feedback */
        post: operations["create_user_feedback_api_feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Check
         * @description 深度健康检查（best-effort）。
         */
        get: operations["health_check_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Live
         * @description Liveness probe (does not check dependencies).
         */
        get: operations["health_live_api_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Ready
         * @description Readiness probe (checks critical dependencies only).
         */
        get: operations["health_ready_api_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/available-filters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Available Filters
         * @description Get available filters for the current subject.
         */
        post: operations["available_filters_api_integrations_openai_available_filters_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/compose-blueprint": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Compose Blueprint
         * @description Search and assemble question IDs from a blueprint.
         */
        post: operations["compose_blueprint_api_integrations_openai_compose_blueprint_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/create-paper": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Paper
         * @description Create a paper from question IDs.
         */
        post: operations["create_paper_api_integrations_openai_create_paper_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/filter-questions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Filter Questions
         * @description Filter questions for OpenAI Function Calling clients.
         */
        post: operations["filter_questions_api_integrations_openai_filter_questions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/papers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Papers
         * @description List papers for the adapter compatibility user.
         */
        get: operations["get_papers_api_integrations_openai_papers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/papers/{paper_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Paper Detail
         * @description Get paper details for the adapter compatibility user.
         */
        get: operations["get_paper_detail_api_integrations_openai_papers__paper_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/question-info/{question_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Question Info
         * @description Get question details for OpenAI Function Calling clients.
         */
        get: operations["get_question_info_api_integrations_openai_question_info__question_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/search-by-keyword": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Search By Keyword
         * @description Search questions by keyword for OpenAI Function Calling clients.
         */
        post: operations["search_by_keyword_api_integrations_openai_search_by_keyword_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/integrations/openai/search-by-knowledge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Search By Knowledge
         * @description Search questions by knowledge point for OpenAI Function Calling clients.
         */
        post: operations["search_by_knowledge_api_integrations_openai_search_by_knowledge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning-plans": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Plans */
        get: operations["list_plans_api_learning_plans_get"];
        put?: never;
        /** Create Plan */
        post: operations["create_plan_api_learning_plans_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning-plans/from-study-archive/{archive_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Plan From Study Archive
         * @description Generate a simple todo list from a StudyArchive (read/practice/review).
         */
        post: operations["create_plan_from_study_archive_api_learning_plans_from_study_archive__archive_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning-plans/items/{item_id}/completed": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Set Item Completed */
        post: operations["set_item_completed_api_learning_plans_items__item_id__completed_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning-plans/{plan_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Plan */
        get: operations["get_plan_api_learning_plans__plan_id__get"];
        put?: never;
        post?: never;
        delete?: never;
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
    "/api/llm-debug": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Llm Debug
         * @description Return recent in-process LLM calls for local debugging.
         */
        get: operations["llm_debug_api_llm_debug_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/generated/{filename}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Generated Media
         * @description Serve locally generated media from `.local/media/generated/`.
         */
        get: operations["get_generated_media_api_media_generated__filename__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/proxy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Proxy Media
         * @description Fetch a remote media URL and cache it on disk for stable rendering.
         *
         *     - Requires an authenticated user (router-level + explicit dep for clarity).
         *     - Returns a cached file if available.
         *     - Downloads and stores into `.local/media/` otherwise.
         */
        get: operations["proxy_media_api_media_proxy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meta": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Meta */
        get: operations["list_meta_api_meta_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meta/{item_type}/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Meta */
        get: operations["get_meta_api_meta__item_type___item_id__get"];
        put?: never;
        /** Set Meta */
        post: operations["set_meta_api_meta__item_type___item_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Metrics
         * @description Prometheus metrics endpoint (authenticated under `/api/metrics`).
         *
         *     Note: the app also exposes an unauthenticated `/metrics` at the root for
         *     Prometheus scraping (see `backend.core.metrics.instrument_app`).
         */
        get: operations["metrics_api_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/model-settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Model Settings
         * @description 返回本地模型配置（API Key 只返回脱敏状态）。
         */
        get: operations["get_model_settings_api_model_settings_get"];
        /**
         * Put Model Settings
         * @description 保存本地模型配置。密钥写入前会加密。
         */
        put: operations["put_model_settings_api_model_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/model-settings/fetch-models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Fetch Model Settings Models */
        post: operations["fetch_model_settings_models_api_model_settings_fetch_models_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Papers List
         * @description 获取试卷列表
         */
        get: operations["get_papers_list_api_papers_get"];
        put?: never;
        /**
         * Create Paper
         * @description 创建试卷
         */
        post: operations["create_paper_api_papers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers/compose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Compose Paper
         * @description Blueprint-based paper composing (teacher-side) with SSE streaming.
         *
         *     Frontend expects events shaped like:
         *     - {type:'step', step: TaskStep}
         *     - {type:'progress', progress:number}
         *     - {type:'result', result: Paper}
         *     - {type:'error', error:string}
         */
        post: operations["compose_paper_api_papers_compose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers/generate-full": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate Full Paper
         * @description 一键 AI 生成整张试卷（返回 SSE 流）。
         */
        post: operations["generate_full_paper_api_papers_generate_full_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers/{paper_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Paper Info
         * @description 获取试卷信息
         */
        get: operations["get_paper_info_api_papers__paper_id__get"];
        put?: never;
        post?: never;
        /**
         * Remove Paper
         * @description 删除试卷
         */
        delete: operations["remove_paper_api_papers__paper_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers/{paper_id}/download-link": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Download Link
         * @description 生成组卷网下载链接（合规：仅提供题目链接）
         */
        get: operations["get_download_link_api_papers__paper_id__download_link_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers/{paper_id}/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Export Paper
         * @description 导出试卷为 Markdown/LaTeX/PDF（写入 `.local/media/generated/` 并返回下载链接）。
         */
        post: operations["export_paper_api_papers__paper_id__export_post"];
        delete?: never;
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
    "/api/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search
         * @description Global full-text search (best-effort).
         */
        get: operations["search_api_search_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/search-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Record Search History
         * @description 记录搜索历史
         */
        post: operations["record_search_history_api_search_history_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/share-links": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Share Link */
        post: operations["create_share_link_api_share_links_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/share/{token}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Share Link Meta */
        get: operations["get_share_link_meta_api_share__token__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/share/{token}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Fetch Shared Content */
        post: operations["fetch_shared_content_api_share__token__content_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/share/{token}/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Validate Share Link */
        post: operations["validate_share_link_api_share__token__validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-archives": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Archives */
        get: operations["list_archives_api_study_archives_get"];
        put?: never;
        /** Create Archive */
        post: operations["create_archive_api_study_archives_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-archives/{archive_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Archive */
        get: operations["get_archive_api_study_archives__archive_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/study-archives/{archive_id}/clone": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Clone Archive */
        post: operations["clone_archive_api_study_archives__archive_id__clone_post"];
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
    "/api/subjects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Subjects List
         * @description 获取支持的学科列表
         */
        get: operations["get_subjects_list_api_subjects_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/subjects/{subject_code}/filters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Subject Filters
         * @description 获取某学科可用筛选项（年级/教材版本/地区/题型等）。
         *
         *     前端期望字段：grades/textbookVersions/provinces/paperTypes/questionTypes。
         */
        get: operations["get_subject_filters_api_subjects__subject_code__filters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/subjects/{subject_code}/knowledge-tree": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Subject Knowledge Tree */
        get: operations["get_subject_knowledge_tree_api_subjects__subject_code__knowledge_tree_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Tasks */
        get: operations["list_tasks_api_tasks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/deepthink": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Deepthink
         * @description Canonical long-task submit endpoint for DeepThink.
         */
        post: operations["submit_deepthink_api_tasks_deepthink_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/essay-evaluations/evaluate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Essay Evaluation
         * @description Canonical long-task submit endpoint for essay evaluation.
         *
         *     The runner persists the result to ``essay_evaluations`` and emits SSE
         *     progress + a final ``done`` event with the structured rubric output.
         */
        post: operations["submit_essay_evaluation_api_tasks_essay_evaluations_evaluate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/export/papers/{paper_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Export Paper Task */
        post: operations["export_paper_task_api_tasks_export_papers__paper_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/export/study-archives/{archive_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Export Study Archive Task */
        post: operations["export_study_archive_task_api_tasks_export_study_archives__archive_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/knowledge-videos/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Knowledge Video
         * @description Canonical long-task submit endpoint for AI-generated Manim knowledge videos.
         */
        post: operations["submit_knowledge_video_api_tasks_knowledge_videos_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/lesson-plans/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Lesson Plan
         * @description Canonical long-task submit endpoint for lesson-plan generation.
         */
        post: operations["submit_lesson_plan_api_tasks_lesson_plans_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/papers/compose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Paper Compose
         * @description Canonical long-task submit endpoint for paper composing.
         */
        post: operations["submit_paper_compose_api_tasks_papers_compose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/papers/generate-full": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Generate Full Paper
         * @description Canonical long-task submit endpoint for one-click full paper generation.
         */
        post: operations["submit_generate_full_paper_api_tasks_papers_generate_full_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/question-evaluate/evaluate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Question Evaluate
         * @description Canonical long-task submit endpoint for question quality evaluation.
         */
        post: operations["submit_question_evaluate_api_tasks_question_evaluate_evaluate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/question-library/crawl": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Question Library Crawl
         * @description Canonical long-task submit endpoint for question-library crawling.
         */
        post: operations["submit_question_library_crawl_api_tasks_question_library_crawl_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/question-library/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Question Library Generate
         * @description Canonical long-task submit endpoint for question-library generation.
         */
        post: operations["submit_question_library_generate_api_tasks_question_library_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/question-library/score": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Question Library Score
         * @description Canonical long-task submit endpoint for question-library scoring.
         */
        post: operations["submit_question_library_score_api_tasks_question_library_score_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/study-materials/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Study Materials
         * @description Canonical long-task submit endpoint for study-materials generation.
         */
        post: operations["submit_study_materials_api_tasks_study_materials_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/study-materials/{task_id}/continue": {
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
         * @description Create a follow-up study-materials task (one bounded continuation iteration).
         */
        post: operations["continue_study_materials_task_api_tasks_study_materials__task_id__continue_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Task Status */
        get: operations["get_task_status_api_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Task */
        post: operations["cancel_task_api_tasks__task_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/pause": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Pause Task */
        post: operations["pause_task_api_tasks__task_id__pause_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resume Task */
        post: operations["resume_task_api_tasks__task_id__resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry Task */
        post: operations["retry_task_api_tasks__task_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Stream Task */
        get: operations["stream_task_api_tasks__task_id__stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List User Templates */
        get: operations["list_user_templates_api_templates_get"];
        put?: never;
        /** Create User Template */
        post: operations["create_user_template_api_templates_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/templates/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export User Templates */
        get: operations["export_user_templates_api_templates_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/templates/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Import User Templates */
        post: operations["import_user_templates_api_templates_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/templates/{template_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get User Template */
        get: operations["get_user_template_api_templates__template_id__get"];
        /** Update User Template */
        put: operations["update_user_template_api_templates__template_id__put"];
        post?: never;
        /** Delete User Template */
        delete: operations["delete_user_template_api_templates__template_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/user-settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get User Settings */
        get: operations["get_user_settings_api_user_settings_get"];
        /** Put User Settings */
        put: operations["put_user_settings_api_user_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/user-settings/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export User Settings */
        get: operations["export_user_settings_api_user_settings_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/user-settings/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Import User Settings */
        post: operations["import_user_settings_api_user_settings_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/wrongbook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Wrongbook */
        get: operations["list_wrongbook_api_wrongbook_get"];
        put?: never;
        /** Upsert Wrongbook Item */
        post: operations["upsert_wrongbook_item_api_wrongbook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/wrongbook/practice": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate Practice Paper
         * @description Create a practice paper from wrongbook questions (filtered by knowledge point / selection).
         */
        post: operations["generate_practice_paper_api_wrongbook_practice_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/wrongbook/{question_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Wrongbook Item */
        delete: operations["delete_wrongbook_item_api_wrongbook__question_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}

