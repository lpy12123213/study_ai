import { useEffect, useState, useCallback } from 'react';
import ChatSidebar from './components/ChatSidebar';
import ChatArea from './components/ChatArea';
import SubjectSelector from './components/SubjectSelector';
import MainLayout from './components/MainLayout';
import Header from './components/Header';
import {
  getConversations,
  createConversation,
  deleteConversation,
  getConversationMessages,
  sendChatMessage,
  Conversation,
  Message,
  ToolResult
} from './services/api';

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);

  const [currentConvId, setCurrentConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  const [chatLoading, setChatLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [currentToolCalls, setCurrentToolCalls] = useState<any[]>([]);
  const [toolResults, setToolResults] = useState<ToolResult[]>([]);

  const [currentSubject, setCurrentSubject] = useState(() => {
    return localStorage.getItem('selectedSubject') || '高中数学';
  });

  const handleSubjectChange = useCallback((subject: string) => {
    setCurrentSubject(subject);
    localStorage.setItem('selectedSubject', subject);
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

  const loadMessages = useCallback(async (convId: number) => {
    setMessagesLoading(true);
    setMessages([]);
    setStreamingContent('');
    setCurrentToolCalls([]);
    setToolResults([]);

    try {
      const data = await getConversationMessages(convId);
      setMessages(data.messages);
    } catch (error) {
      console.error('Failed to load messages:', error);
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  const handleSelectConversation = useCallback((id: number) => {
    setCurrentConvId(id);
    loadMessages(id);
  }, [loadMessages]);

  const handleCreateConversation = useCallback(async () => {
    try {
      const data = await createConversation();
      setCurrentConvId(data.id);
      setMessages([]);
      setStreamingContent('');
      setCurrentToolCalls([]);
      setToolResults([]);
      loadConversations();
    } catch (error) {
      console.error('Failed to create conversation:', error);
      alert('创建对话失败');
    }
  }, [loadConversations]);

  const handleDeleteConversation = useCallback(async (id: number) => {
    if (!confirm('确定删除这个对话吗？')) return;

    try {
      await deleteConversation(id);
      if (currentConvId === id) {
        setCurrentConvId(null);
        setMessages([]);
      }
      loadConversations();
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      alert('删除失败');
    }
  }, [currentConvId, loadConversations]);

  const handleSendMessage = useCallback(async (message: string) => {
    if (!currentConvId || chatLoading) return;

    const userMessage: Message = {
      id: Date.now(),
      role: 'user',
      content: message,
      created_at: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMessage]);

    setChatLoading(true);
    setStreamingContent('');
    setCurrentToolCalls([]);
    setToolResults([]);

    let allToolCalls: any[] = [];

    try {
      await sendChatMessage(currentConvId, message, (chunk) => {
        const { type } = chunk;
        console.log('[App] Processing chunk:', type, chunk);

        if (type === 'iteration') {
          setStreamingContent(`AI 正在进行第${chunk.round}轮操作...`);
        } else if (type === 'assistant') {
          if (chunk.tool_calls) {
            allToolCalls = [...allToolCalls, ...chunk.tool_calls];
            const iterationPrefix = chunk.iteration > 1 ? `[第${chunk.iteration}轮] ` : '';
            setStreamingContent(iterationPrefix + (chunk.content || ''));
            setCurrentToolCalls(allToolCalls);
            const newResults = chunk.tool_calls.map((tc: any) => ({
              tool_call_id: tc.id,
              tool_name: tc.function.name,
              status: 'pending' as const,
              iteration: chunk.iteration
            }));
            setToolResults(prev => [...prev, ...newResults]);
          } else {
            const assistantMessage: Message = {
              id: Date.now() + 1,
              role: 'assistant',
              content: chunk.content || '',
              created_at: new Date().toISOString()
            };
            setMessages(prev => [...prev, assistantMessage]);
            setStreamingContent('');
          }
        } else if (type === 'tool_start') {
          setToolResults(prev =>
            prev.map(tr =>
              tr.tool_call_id === chunk.tool_call_id
                ? { ...tr, status: 'running' as const, arguments: chunk.arguments }
                : tr
            )
          );
        } else if (type === 'tool_result') {
          setToolResults(prev =>
            prev.map(tr =>
              tr.tool_call_id === chunk.tool_call_id
                ? { ...tr, status: 'completed' as const, result: chunk.result }
                : tr
            )
          );
        } else if (type === 'stream_start') {
          setStreamingContent('');
        } else if (type === 'text_delta') {
          setStreamingContent(prev => prev + (chunk.content || ''));
        } else if (type === 'assistant_final') {
          const assistantMessage: Message = {
            id: Date.now() + 1,
            role: 'assistant',
            content: chunk.content || '(AI正在处理...)',
            tool_calls: allToolCalls.length > 0 ? allToolCalls : undefined,
            created_at: new Date().toISOString()
          };
          setMessages(prev => [...prev, assistantMessage]);
          setStreamingContent('');
          setCurrentToolCalls([]);
        } else if (type === 'error') {
          alert(chunk.content || '发生错误');
        }
      }, currentSubject);

      loadConversations();
    } catch (error) {
      console.error('Failed to send message:', error);
      alert('发送失败，请重试');
    } finally {
      setChatLoading(false);
    }
  }, [currentConvId, chatLoading, loadConversations, currentSubject]);

  return (
    <MainLayout
      header={
        <Header
          rightContent={
            <SubjectSelector value={currentSubject} onChange={handleSubjectChange} />
          }
        />
      }
      sidebar={
        <ChatSidebar
          conversations={conversations}
          currentId={currentConvId}
          onSelect={handleSelectConversation}
          onCreate={handleCreateConversation}
          onDelete={handleDeleteConversation}
          loading={conversationsLoading}
        />
      }
    >
      {currentConvId ? (
        <ChatArea
          messages={messages}
          toolResults={toolResults}
          onSend={handleSendMessage}
          loading={chatLoading || messagesLoading}
          streamingContent={streamingContent}
          currentToolCalls={currentToolCalls}
        />
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-500">
          <div className="text-8xl mb-6 animate-bounce">🤖</div>
          <div className="text-2xl font-bold mb-2 text-white">欢迎使用智能组卷助手</div>
          <div className="text-sm text-center max-w-md mb-8 text-slate-400">
            创建新对话或选择历史对话开始组卷
          </div>
          <button
            onClick={handleCreateConversation}
            className="px-8 py-3 bg-primary hover:bg-primary-hover text-white font-semibold rounded-xl transition-all shadow-lg shadow-primary/25 hover:shadow-primary/40 hover:-translate-y-0.5 active:translate-y-0"
          >
            发起新对话
          </button>
        </div>
      )}
    </MainLayout>
  );
}
