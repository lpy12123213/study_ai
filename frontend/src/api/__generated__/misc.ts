// AUTO-GENERATED. Do not edit by hand.
// Paths for the `misc` domain.
// Regenerate via `npm run gen:api`.

import type { components, operations } from './components'

export type { components, operations }

export interface paths {
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
}
