import ChatSidebar from '@/components/ChatSidebar';
import ChatArea from '@/components/ChatArea';
import SubjectSelector from '@/components/SubjectSelector';
import MainLayout from '@/components/MainLayout';
import Header from '@/components/Header';
import { useChatApp } from '@/features/chat/useChatApp';

export default function App() {
  const {
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
  } = useChatApp();

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
