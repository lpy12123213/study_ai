import { useCallback, useState, useRef } from 'react';
import {
    ReactFlow,
    Controls,
    Background,
    BackgroundVariant,
    useNodesState,
    useEdgesState,
    addEdge,
    Panel,
} from '@xyflow/react';
import type { Connection, Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import MessageNodeComponent, { type MessageNode } from './MessageNode';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Send, Loader2 } from 'lucide-react';

const nodeTypes = {
    message: MessageNodeComponent,
};

const initialNodes: MessageNode[] = [];
const initialEdges: Edge[] = [];

export default function ChatCanvas() {
    const [nodes, setNodes, onNodesChange] = useNodesState<MessageNode>(initialNodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const conversationIdRef = useRef<number | null>(null);

    const onConnect = useCallback(
        (params: Connection) => setEdges((eds) => addEdge(params, eds)),
        [setEdges]
    );

    const getNextNodePosition = useCallback(() => {
        if (nodes.length === 0) {
            return { x: 250, y: 50 };
        }
        const lastNode = nodes[nodes.length - 1];
        return { x: lastNode.position.x, y: lastNode.position.y + 180 };
    }, [nodes]);

    const handleFork = useCallback((nodeId: string) => {
        console.log('Fork from node:', nodeId);
        setInput('');
    }, []);

    const addMessageNode = useCallback(
        (role: 'user' | 'assistant', content: string, parentId?: string) => {
            const position = getNextNodePosition();
            const newNodeId = `node-${Date.now()}`;

            const newNode: MessageNode = {
                id: newNodeId,
                type: 'message',
                position,
                data: {
                    role,
                    content,
                    onFork: role === 'assistant' ? () => handleFork(newNodeId) : undefined,
                },
            };

            setNodes((nds) => [...nds, newNode] as MessageNode[]);

            if (parentId) {
                const newEdge: Edge = {
                    id: `edge-${parentId}-${newNodeId}`,
                    source: parentId,
                    target: newNodeId,
                    animated: true,
                    style: { stroke: 'hsl(var(--muted-foreground))' },
                };
                setEdges((eds) => [...eds, newEdge]);
            }

            return newNodeId;
        },
        [getNextNodePosition, setNodes, setEdges, handleFork]
    );

    const handleSend = useCallback(async () => {
        if (!input.trim() || isLoading) return;

        const userMessage = input.trim();
        setInput('');
        setIsLoading(true);

        const lastNodeId = nodes.length > 0 ? nodes[nodes.length - 1].id : undefined;
        const userNodeId = addMessageNode('user', userMessage, lastNodeId);

        try {
            // Create conversation if not exists
            if (!conversationIdRef.current) {
                const createRes = await fetch('http://localhost:8000/api/conversations', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: userMessage.slice(0, 30) }),
                });
                if (!createRes.ok) {
                    throw new Error('Failed to create conversation');
                }
                const convData = await createRes.json();
                conversationIdRef.current = convData.id;
            }

            const response = await fetch('http://localhost:8000/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    conversation_id: conversationIdRef.current,
                    message: userMessage,
                    subject: '高中数学',
                }),
            });

            if (!response.ok) {
                throw new Error('API request failed');
            }

            const reader = response.body?.getReader();
            const decoder = new TextDecoder();
            let assistantContent = '';
            let assistantNodeId: string | null = null;

            if (reader) {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split('\n');

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const data = line.slice(6);
                            if (data === '[DONE]') continue;

                            try {
                                const parsed = JSON.parse(data);
                                if (parsed.type === 'text_delta' && parsed.content) {
                                    assistantContent += parsed.content;

                                    if (!assistantNodeId) {
                                        assistantNodeId = addMessageNode('assistant', assistantContent, userNodeId);
                                    }
                                    setNodes((nds) =>
                                        nds.map((n) =>
                                            n.id === assistantNodeId
                                                ? { ...n, data: { ...n.data, content: assistantContent, isStreaming: true } }
                                                : n
                                        ) as MessageNode[]
                                    );
                                }
                            } catch {
                                // Ignore JSON parse errors
                            }
                        }
                    }
                }
            }

            if (assistantNodeId) {
                setNodes((nds) =>
                    nds.map((n) =>
                        n.id === assistantNodeId
                            ? { ...n, data: { ...n.data, isStreaming: false } }
                            : n
                    ) as MessageNode[]
                );
            } else {
                addMessageNode('assistant', 'Sorry, I could not process your request.', userNodeId);
            }
        } catch (error) {
            console.error('Chat error:', error);
            addMessageNode('assistant', 'Error: Could not connect to the AI service. Please ensure the backend is running.', userNodeId);
        } finally {
            setIsLoading(false);
        }
    }, [input, isLoading, nodes, addMessageNode, setNodes]);

    return (
        <div className="h-full w-full flex flex-col">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                nodeTypes={nodeTypes}
                fitView
                className="flex-1"
                proOptions={{ hideAttribution: true }}
            >
                <Controls />
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} />

                <Panel position="bottom-center" className="w-full max-w-2xl mb-4">
                    <div className="flex gap-2 p-4 bg-card/80 backdrop-blur-sm border rounded-xl shadow-lg">
                        <Input
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                            placeholder="输入问题或指令，例如：帮我找20道二次函数的选择题"
                            className="flex-1"
                            disabled={isLoading}
                        />
                        <Button onClick={handleSend} disabled={isLoading || !input.trim()}>
                            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                        </Button>
                    </div>
                </Panel>

                <Panel position="top-center" className="mt-4">
                    <div className="px-4 py-2 bg-card/80 backdrop-blur-sm border rounded-lg shadow-sm">
                        <h2 className="text-sm font-medium text-muted-foreground">
                            AI 组卷对话 · 拖动画布平移，滚轮缩放
                        </h2>
                    </div>
                </Panel>
            </ReactFlow>
        </div>
    );
}
