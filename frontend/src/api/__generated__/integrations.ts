// AUTO-GENERATED. Do not edit by hand.
// Paths for the `integrations` domain.
// Regenerate via `npm run gen:api`.

import type { components, operations } from './components'

export type { components, operations }

export interface paths {
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
}
