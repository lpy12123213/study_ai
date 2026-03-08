# Product Foundation (Tasks 161–182) Design

**Goal:** Implement the remaining roadmap items in `nextstep.csv` (161–182) via a shared “product foundation” so tasks, search, metadata, settings, sharing, and UX behaviors are consistent across features.

**Scope mapping**
- `161/165/166/182`: Global task center + unified progress/ETA + notifications + self-healing actions
- `162/169`: Favorite/pin/tags + fast indexed search with highlight + sidebar filters
- `163/173/174`: Reuse config (“再来一次”) + form drafts + template library
- `167/178`: Cross-device settings sync + accessibility/display preferences
- `170`: Offline read-only cache + weak-network UX
- `171`: Public read-only share links + QR code
- `172`: Learning plan + reminders
- `175`: Export center + export queue (as tasks)
- `176`: Annotations/notes on study materials & papers + filter + jump-to-anchor
- `177`: Feedback reporting with context + status tracking
- `179`: Learning dashboard + CSV export
- `180`: Wrongbook + practice generation (as tasks)
- `181`: Diff/compare view + rollback/save-as-new

---

## Architecture

### Backend
1. **Unified persisted tasks**
   - Store all long-running activities as rows in `tasks` and append streaming events into `task_events`.
   - Keep existing domain streaming endpoints for compatibility, but *also* record all events to the unified tables.
   - `GET /api/tasks` becomes the authoritative list/details surface for the UI task center.

2. **Item metadata (favorite/pin/tags)**
   - Use a generic `user_item_meta` table for `conversation/paper/study_archive/task/lesson_plan/...`.
   - Provide indexed tag filtering and fast prefix/title search; full-text search uses SQLite FTS5 when available.

3. **Cross-device settings**
   - Persist per-user settings JSON in `user_settings` and expose get/update/export/import endpoints.

4. **Sharing**
   - `share_links` store `{token,item_type,item_id,expires_at,password_hash}`.
   - Public read-only endpoint returns content without auth if the token is valid; optional password check.

5. **Product features tables**
   - Learning plans: `learning_plans`, `learning_plan_items`
   - Annotations: `annotations`
   - Feedback: `feedback_reports`
   - Templates: `user_templates`
   - Wrongbook: `wrong_questions`

### Frontend
1. **Task center UI**
   - New page to list tasks by status/type + open task detail timeline.
   - Sidebar shows “Running” tasks section with same statuses and actions.
   - Unified progress/ETA component + heartbeat status.

2. **Notifications**
   - In-site notification center with unread badge.
   - Optional browser notifications (Notification API) controlled via synced settings.

3. **Command palette + shortcuts**
   - Global command palette (Cmd/Ctrl+K by default) with navigation and common actions.
   - Shortcut bindings configurable in settings; defaults avoid common IME conflicts.

4. **Search**
   - Global search page/modal.
   - Results deep-link to pages and highlight the matched content/anchor.

5. **Drafts + templates**
   - Draft autosave to local storage with size/count limits.
   - Templates CRUD + import/export; apply templates without breaking validation.

6. **Offline**
   - Cache recently opened items in IndexedDB with hard limits and LRU eviction.
   - Offline mode marks pages read-only and disables writes; reconnect refreshes.

---

## Data model (high level)
- `tasks(id,user_id,type,title,status,progress,request_json,result_ref_json,error_json,created_at,updated_at,started_at,ended_at,parent_task_id)`
- `task_events(id,task_id,seq,event_type,payload_json,created_at)`
- `user_item_meta(id,user_id,item_type,item_id,starred,pinned,tags_json,created_at,updated_at)`
- `user_settings(user_id,settings_json,created_at,updated_at)`
- `share_links(token,user_id,item_type,item_id,expires_at,password_hash,created_at)`
- `learning_plans(id,user_id,title,archived,created_at,updated_at)`
- `learning_plan_items(id,plan_id,title,description,due_at,completed,completed_at,sort_order,source_ref_json,created_at,updated_at)`
- `annotations(id,user_id,item_type,item_id,anchor,snippet,content,tags_json,created_at,updated_at)`
- `feedback_reports(id,user_id,title,description,context_json,status,created_at,updated_at)`
- `user_templates(id,user_id,template_type,name,body_json,created_at,updated_at)`
- `wrong_questions(id,user_id,question_id,subject,knowledge_point,mastery,note,tags_json,source_ref_json,created_at,updated_at)`

---

## Key UX behaviors
- **Heartbeat:** any running task shows activity at least every 5 seconds (UI or SSE ping).
- **Retry/self-heal:** backend emits standard error codes + `recommend_actions`; frontend shows one-click actions and records action result as a new task event.
- **Consistency:** sidebar, task center, and feature pages display the same task status and title.
- **Performance:** search endpoints use indexes/FTS and return only top 50 within strict limits; long lists degrade animation.

