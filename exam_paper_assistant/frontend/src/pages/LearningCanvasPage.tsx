import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { formatDistanceToNow } from "date-fns";
import { ChevronLeft, ChevronRight, History, Plus, Save, Sparkles } from "lucide-react";
import type { Editor } from "tldraw";
import { Tldraw, createTLStore, defaultShapeUtils, getSnapshot, loadSnapshot } from "tldraw";
import "tldraw/tldraw.css";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { canvasApi } from "@/api/canvas";
import { useCanvasBoard, useCanvasBoards, useCreateCanvasBoard, useCreateCanvasVersion, useUpdateCanvasBoard } from "@/hooks/useCanvas";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { useSubjects } from "@/hooks/useSubjects";
import { cn } from "@/lib/utils";
import { QuestionCardShapeUtil } from "@/features/learning-canvas/shapes/QuestionCardShapeUtil";

function asBoardId(raw: string | undefined): number | null {
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function relativeTime(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  return formatDistanceToNow(dt, { addSuffix: true });
}

export default function LearningCanvasPage() {
  const params = useParams();
  const navigate = useNavigate();

  const boardId = useMemo(() => asBoardId(params.boardId), [params.boardId]);

  const [boardQuery, setBoardQuery] = useState("");

  const [leftPanelCollapsed, setLeftPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_learn_left_panel_collapsed",
    false,
  );
  const [rightPanelCollapsed, setRightPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_learn_right_panel_collapsed",
    false,
  );

  const boardsQuery = useCanvasBoards({ q: boardQuery, limit: 100 });
  const boardDetailQuery = useCanvasBoard(boardId);
  const updateBoard = useUpdateCanvasBoard();
  const createBoard = useCreateCanvasBoard();
  const createVersion = useCreateCanvasVersion();

  const subjectsQuery = useSubjects();
  const subjects = useMemo(() => subjectsQuery.data ?? [], [subjectsQuery.data]);

  const [subjectName, setSubjectName] = useLocalStorageState<string>(
    "epa_learn_subject_name",
    "高中数学",
  );

  const [modelOverride, setModelOverride] = useLocalStorageState<string>(
    "epa_learn_model_override",
    "google/gemini-3-flash-preview",
  );

  const [prompt, setPrompt] = useState("");
  const [pickCount, setPickCount] = useState<number>(3);
  const [isPicking, setIsPicking] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);

  const editorRef = useRef<Editor | null>(null);
  const autosaveTimerRef = useRef<number | null>(null);
  const loadedBoardIdRef = useRef<number | null>(null);
  const boardRevisionRef = useRef<number>(1);
  const isApplyingSnapshotRef = useRef<boolean>(false);

  const shapeUtils = useMemo(() => [...defaultShapeUtils, QuestionCardShapeUtil], []);
  const store = useMemo(() => createTLStore({ shapeUtils }), [shapeUtils, boardId]);

  const board = boardDetailQuery.data ?? null;

  useEffect(() => {
    if (!board) return;
    boardRevisionRef.current = board.revision ?? 1;
  }, [board?.revision]);

  useEffect(() => {
    if (!boardId) return;
    if (!board) return;
    if (loadedBoardIdRef.current === boardId) return;
    loadedBoardIdRef.current = boardId;

    const hasSnapshot = board.snapshot && Object.keys(board.snapshot).length > 0;
    if (!hasSnapshot) return;

    isApplyingSnapshotRef.current = true;
    try {
      loadSnapshot(store, board.snapshot as never);
    } finally {
      isApplyingSnapshotRef.current = false;
    }
  }, [boardId, board, store]);

  const onMount = useCallback((editor: Editor) => {
    editorRef.current = editor;
  }, []);

  const flushAutosave = useCallback(async () => {
    if (!boardId) return;
    if (isApplyingSnapshotRef.current) return;

    const snapshot = getSnapshot(store);
    const payload = {
      snapshot: snapshot as unknown as Record<string, unknown>,
      expected_revision: boardRevisionRef.current,
    };

    const result = await updateBoard.mutateAsync({ boardId, payload });
    if ("conflict" in result && result.conflict) {
      const server = result.server_board;
      boardRevisionRef.current = server.revision ?? boardRevisionRef.current;
      if (server.snapshot && Object.keys(server.snapshot).length > 0) {
        isApplyingSnapshotRef.current = true;
        try {
          loadSnapshot(store, server.snapshot as never);
        } finally {
          isApplyingSnapshotRef.current = false;
        }
      }
      return;
    }

    if ("board" in result && result.board) {
      boardRevisionRef.current = result.board.revision ?? boardRevisionRef.current;
    }
  }, [boardId, store, updateBoard]);

  const scheduleAutosave = useCallback(() => {
    if (!boardId) return;
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
    }
    autosaveTimerRef.current = window.setTimeout(() => {
      autosaveTimerRef.current = null;
      void flushAutosave();
    }, 900);
  }, [boardId, flushAutosave]);

  useEffect(() => {
    if (!boardId) return;
    const unlisten = store.listen(() => {
      if (isApplyingSnapshotRef.current) return;
      scheduleAutosave();
    });
    return () => {
      try {
        unlisten();
      } catch {
        // ignore
      }
    };
  }, [boardId, store, scheduleAutosave]);

  const handleCreateBoard = async () => {
    const created = await createBoard.mutateAsync({
      title: "新画布",
      subject: subjectName,
    });
    navigate(`/learn/${created.board.id}`);
  };

  useEffect(() => {
    if (boardId) return;
    const boards = boardsQuery.data?.boards ?? [];
    if (!boards.length) return;
    navigate(`/learn/${boards[0].id}`, { replace: true });
  }, [boardId, boardsQuery.data?.boards, navigate]);

  const handleCreateVersion = async () => {
    if (!boardId) return;
    await flushAutosave();
    await createVersion.mutateAsync(boardId);
  };

  const handleManualSave = async () => {
    if (!boardId) return;
    await flushAutosave();
  };

  const handlePickQuestions = async () => {
    if (!boardId) return;
    const requirement = prompt.trim();
    if (!requirement) return;
    const editor = editorRef.current;
    if (!editor) {
      setPickError("画布尚未初始化，请稍后重试。");
      return;
    }

    setPickError(null);
    setIsPicking(true);
    try {
      const resp = await canvasApi.pickQuestions(boardId, {
        requirement,
        subject: subjectName,
        count: pickCount,
        model: modelOverride,
      });

      const okQuestions = (resp.questions ?? []).filter((q) => q.success && q.stem_html);
      if (!okQuestions.length) {
        setPickError("没有拿到可渲染的题目结果（可能需要先登录组卷网，或换个关键词）。");
        return;
      }

      const viewport = editor.getViewportPageBounds();
      const startX = viewport.x + 80;
      const startY = viewport.y + 80;

      const cardW = 520;
      const cardH = 320;
      const gapX = 40;
      const gapY = 40;

      for (let idx = 0; idx < okQuestions.length; idx += 1) {
        const q = okQuestions[idx];
        const col = idx % 2;
        const row = Math.floor(idx / 2);
        editor.createShape({
          type: "question-card",
          x: startX + col * (cardW + gapX),
          y: startY + row * (cardH + gapY),
          props: {
            w: cardW,
            h: cardH,
            questionId: q.question_id,
            title: q.title || `题目 ${q.question_id}`,
            meta: q.meta || "",
            html: q.stem_html,
          },
        });
      }

      setPrompt("");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setPickError(msg);
    } finally {
      setIsPicking(false);
    }
  };

  return (
    <div className="h-full flex bg-muted/20">
      {/* Boards */}
      <aside
        className={cn(
          "shrink-0 border-r bg-background/60 backdrop-blur-sm flex flex-col overflow-hidden transition-[width] duration-200 ease-in-out",
          leftPanelCollapsed ? "w-14" : "w-[300px]",
        )}
      >
        {leftPanelCollapsed ? (
          <div className="h-full flex flex-col items-center gap-2 p-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => setLeftPanelCollapsed(false)}
              title="展开左侧面板"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            <div className="h-px w-7 bg-border my-1" />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => void handleCreateBoard()}
              title="新建画布"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <>
            <div className="p-4 border-b space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 font-semibold">
                  <Sparkles className="h-4 w-4 text-primary" />
                  学习画布
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    className="gap-1.5"
                    onClick={() => void handleCreateBoard()}
                  >
                    <Plus className="h-4 w-4" />
                    新建
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9"
                    onClick={() => setLeftPanelCollapsed(true)}
                    title="折叠左侧面板"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <Input
                value={boardQuery}
                onChange={(e) => setBoardQuery(e.target.value)}
                placeholder="搜索画布..."
              />
            </div>

            <div className="flex-1 overflow-auto p-3 space-y-2">
              {(boardsQuery.data?.boards ?? []).map((b) => {
                const active = b.id === boardId;
                return (
                  <button
                    key={b.id}
                    className={cn(
                      "w-full text-left rounded-lg border p-3 transition-colors",
                      active ? "border-primary bg-primary/5" : "hover:bg-muted/40",
                    )}
                    onClick={() => navigate(`/learn/${b.id}`)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium truncate">{b.title || `画布 #${b.id}`}</div>
                        <div className="text-xs text-muted-foreground truncate mt-0.5">
                          {b.subject || "未指定学科"}
                        </div>
                      </div>
                      <div className="text-[10px] text-muted-foreground tabular-nums">
                        r{b.revision}
                      </div>
                    </div>
                    {b.updated_at ? (
                      <div className="text-[10px] text-muted-foreground/70 mt-2">
                        {relativeTime(b.updated_at)}
                      </div>
                    ) : null}
                  </button>
                );
              })}
              {!boardsQuery.isLoading && (boardsQuery.data?.boards?.length ?? 0) === 0 ? (
                <Card className="p-4 text-sm text-muted-foreground text-center">
                  还没有画布，点击“新建”开始。
                </Card>
              ) : null}
            </div>
          </>
        )}
      </aside>

      {/* Canvas */}
      <section className="min-w-0 flex-1 flex flex-col">
        <div className="h-12 border-b bg-background/70 backdrop-blur-sm px-4 flex items-center justify-between">
          <div className="min-w-0">
            <div className="font-medium truncate">
              {board?.title || (boardId ? `画布 #${boardId}` : "学习画布")}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => void handleCreateVersion()}
              disabled={!boardId || createVersion.isPending}
              title="保存版本快照"
            >
              <History className="h-4 w-4" />
              版本
            </Button>
            <Button
              size="sm"
              className="gap-2"
              onClick={() => void handleManualSave()}
              disabled={!boardId || updateBoard.isPending}
            >
              <Save className="h-4 w-4" />
              保存
            </Button>
          </div>
        </div>

        <div className="flex-1 min-h-0 bg-muted/30">
          <Tldraw
            key={`board-${boardId ?? "none"}`}
            store={store}
            shapeUtils={shapeUtils}
            autoFocus
            onMount={onMount}
          />
        </div>
      </section>

      {/* AI Panel */}
      <aside
        className={cn(
          "shrink-0 border-l bg-background/60 backdrop-blur-sm flex flex-col overflow-hidden transition-[width] duration-200 ease-in-out",
          rightPanelCollapsed ? "w-14" : "w-[380px]",
        )}
      >
        {rightPanelCollapsed ? (
          <div className="h-full flex flex-col items-center gap-2 p-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => setRightPanelCollapsed(false)}
              title="展开右侧面板"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="h-px w-7 bg-border my-1" />
            <div className="flex-1" />
            <Sparkles className="h-4 w-4 text-primary/70" />
          </div>
        ) : (
          <>
            <div className="p-4 border-b flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-semibold">AI 学习助手</div>
                <div className="text-xs text-muted-foreground mt-1 truncate">
                  默认模型：<span className="font-mono">{modelOverride}</span>
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 shrink-0"
                onClick={() => setRightPanelCollapsed(true)}
                title="折叠右侧面板"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>

            <div className="flex-1 overflow-auto p-4 space-y-4">
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">学科</div>
                <select
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                  value={subjectName}
                  onChange={(e) => setSubjectName(e.target.value)}
                >
                  {subjects.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name}
                    </option>
                  ))}
                  {!subjects.length ? <option value={subjectName}>{subjectName}</option> : null}
                </select>
              </div>

              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">模型（可改）</div>
                <Input value={modelOverride} onChange={(e) => setModelOverride(e.target.value)} />
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => setModelOverride("google/gemini-3-flash-preview")}
                  >
                    Gemini 3 Flash
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-medium text-muted-foreground">选题需求</div>
                  <div className="text-xs text-muted-foreground">数量</div>
                </div>
                <div className="flex items-start gap-2">
                  <Textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="例如：高一函数单调性，含综合应用，难度中等，3道"
                    className="min-h-[84px]"
                  />
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={pickCount}
                    onChange={(e) => setPickCount(Number(e.target.value) || 1)}
                    className="w-[88px]"
                  />
                </div>
                <Button
                  className="w-full gap-2"
                  disabled={!boardId || !prompt.trim() || isPicking}
                  onClick={() => void handlePickQuestions()}
                >
                  <Sparkles className="h-4 w-4" />
                  {isPicking ? "选题中..." : "AI 选题上板"}
                </Button>
                {pickError ? (
                  <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
                    {pickError}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="p-4 border-t text-[10px] text-muted-foreground/70">
              画布自动保存：停止编辑约 1 秒后保存；你也可以手动点“保存”或生成版本快照。
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
