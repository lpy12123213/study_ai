import { useCallback, useEffect, useState } from 'react';
import {
  createConversation,
  deleteConversation,
  getConversationMessages,
  getConversations,
  sendChatMessage,
  type Conversation,
  type Message,
  type ToolCall,
  type ToolResult,
} from '@/api';

const SUBJECT_STORAGE_KEY = 'selectedSubject';
const DEFAULT_SUBJECT = '高中数学';

function getInitialSubject(): string {
  return localStorage.getItem(SUBJECT_STORAGE_KEY) || DEFAULT_SUBJECT;
}

export function useChatApp() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);

  const [currentConvId, setCurrentConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  const [chatLoading, setChatLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [currentToolCalls, setCurrentToolCalls] = useState<ToolCall[]>([]);
  const [toolResults, setToolResults] = useState<ToolResult[]>([]);

  const [currentSubject, setCurrentSubject] = useState(getInitialSubject);

  const handleSubjectChange = useCallback((subject: string) => {
    setCurrentSubject(subject);
    localStorage.setItem(SUBJECT_STORAGE_KEY, subject);
  }, []);

  const resetChatRuntime = useCallback(() => {
    setStreamingContent('');
    setCurrentToolCalls([]);
    setToolResults([]);
  }, []);

  const loadConversations = useCallback(async () => {
    setConversationsLoading(true);
    try {
      const data = await getConversations();
      setConversations(data);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    } finally {
      setConversationsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  const loadMessages = useCallback(
    async (convId: number) => {
      setMessagesLoading(true);
      setMessages([]);
      resetChatRuntime();

      try {
        const data = await getConversationMessages(convId);
        setMessages(data.messages);
      } catch (error) {
        console.error('Failed to load messages:', error);
      } finally {
        setMessagesLoading(false);
      }
    },
    [resetChatRuntime]
  );

  const handleSelectConversation = useCallback(
    (id: number) => {
      setCurrentConvId(id);
      loadMessages(id);
    },
    [loadMessages]
  );

  const handleCreateConversation = useCallback(async () => {
    try {
      const data = await createConversation();
      setCurrentConvId(data.id);
      setMessages([]);
      resetChatRuntime();
      loadConversations();
    } catch (error) {
      console.error('Failed to create conversation:', error);
      alert('创建对话失败');
    }
  }, [loadConversations, resetChatRuntime]);

  const handleDeleteConversation = useCallback(
    async (id: number) => {
      if (!confirm('确定删除这个对话吗？')) return;

      try {
        await deleteConversation(id);
        if (currentConvId === id) {
          setCurrentConvId(null);
          setMessages([]);
          resetChatRuntime();
        }
        loadConversations();
      } catch (error) {
        console.error('Failed to delete conversation:', error);
        alert('删除失败');
      }
    },
    [currentConvId, loadConversations, resetChatRuntime]
  );

  const handleSendMessage = useCallback(
    async (message: string) => {
      if (!currentConvId || chatLoading) return;

      const userMessage: Message = {
        id: Date.now(),
        role: 'user',
        content: message,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);

      setChatLoading(true);
      resetChatRuntime();

      let allToolCalls: ToolCall[] = [];

      try {
        await sendChatMessage(
          currentConvId,
          message,
          (chunk) => {
            if (chunk.type === 'iteration') {
              setStreamingContent(`AI 正在进行第${chunk.round}轮操作...`);
              return;
            }

            if (chunk.type === 'assistant') {
              if (chunk.tool_calls) {
                allToolCalls = [...allToolCalls, ...chunk.tool_calls];
                const iteration = chunk.iteration ?? 1;
                const iterationPrefix = iteration > 1 ? `[第${iteration}轮] ` : '';
                setStreamingContent(iterationPrefix + (chunk.content || ''));
                setCurrentToolCalls(allToolCalls);

                const newResults: ToolResult[] = chunk.tool_calls.map((tc) => ({
                  tool_call_id: tc.id,
                  tool_name: tc.function.name,
                  status: 'pending' as const,
                  iteration,
                }));
                setToolResults((prev) => [...prev, ...newResults]);
              }
              return;
            }

            if (chunk.type === 'tool_start') {
              setToolResults((prev) =>
                prev.map((tr) =>
                  tr.tool_call_id === chunk.tool_call_id
                    ? { ...tr, status: 'running' as const, arguments: chunk.arguments }
                    : tr
                )
              );
              return;
            }

            if (chunk.type === 'tool_result') {
              setToolResults((prev) =>
                prev.map((tr) =>
                  tr.tool_call_id === chunk.tool_call_id
                    ? { ...tr, status: 'completed' as const, result: chunk.result }
                    : tr
                )
              );
              return;
            }

            if (chunk.type === 'stream_start') {
              setStreamingContent('');
              return;
            }

            if (chunk.type === 'text_delta') {
              setStreamingContent((prev) => prev + (chunk.content || ''));
              return;
            }

            if (chunk.type === 'assistant_final') {
              const assistantMessage: Message = {
                id: Date.now() + 1,
                role: 'assistant',
                content: chunk.content || '(AI正在处理...)',
                tool_calls: allToolCalls.length > 0 ? allToolCalls : undefined,
                created_at: new Date().toISOString(),
              };
              setMessages((prev) => [...prev, assistantMessage]);
              setStreamingContent('');
              setCurrentToolCalls([]);
              return;
            }

            if (chunk.type === 'error') {
              alert(chunk.content || '发生错误');
            }
          },
          currentSubject
        );

        loadConversations();
      } catch (error) {
        console.error('Failed to send message:', error);
        alert('发送失败，请重试');
      } finally {
        setChatLoading(false);
      }
    },
    [chatLoading, currentConvId, currentSubject, loadConversations, resetChatRuntime]
  );

  return {
    conversations,
    conversationsLoading,
    currentConvId,
    messages,
    messagesLoading,
    chatLoading,
    streamingContent,
    currentToolCalls,
    toolResults,
    currentSubject,
    handleSubjectChange,
    handleSelectConversation,
    handleCreateConversation,
    handleDeleteConversation,
    handleSendMessage,
    reloadConversations: loadConversations,
  };
}

