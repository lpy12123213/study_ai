/**
 * 空态对话模式（规划 §10）：提示策略前缀，不是独立模型或后端契约。
 * 点击后仅把策略前缀填入输入框，用户补全问题后按普通消息发送。
 */
export interface ComposerMode {
  id: string;
  label: string;
  /** 填入输入框的提示前缀 */
  prefix: string;
}

export const COMPOSER_MODES: ComposerMode[] = [
  { id: "explain", label: "讲清概念", prefix: "请讲清这个概念：" },
  { id: "derive", label: "陪我推导", prefix: "请陪我一步步推导：" },
  { id: "practice", label: "生成练习", prefix: "请生成练习题：" },
  { id: "notes", label: "整理笔记", prefix: "请帮我整理笔记：" },
];
