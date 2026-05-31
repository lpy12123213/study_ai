// AUTO-GENERATED. Do not edit by hand.
// Paths for the `workspace` domain.
// Regenerate via `npm run gen:api`.

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
