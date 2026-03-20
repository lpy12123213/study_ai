export function humanizeAiGenerateTaskError(raw: string): { display: string; code?: string } {
  const code = String(raw || '').trim()
  if (!code) return { display: '' }

  if (code.startsWith('llm_request_failed')) {
    const provider = code.match(/\bprovider=([^\s]+)/)?.[1] || ''
    const model = code.match(/\bmodel=([^\s]+)/)?.[1] || ''
    const message = code.match(/\bmsg=(.+)$/)?.[1]?.trim() || code.match(/\berr=(.+)$/)?.[1]?.trim() || ''
    const mismatch =
      /model not found|not deployed|inaccessible|does not exist|unknown model/i.test(message) ||
      Boolean(provider && model)

    if (mismatch) {
      const providerLabel = provider || '当前 Provider'
      const modelLabel = model || '当前模型'
      return {
        display: `大模型路由配置不可用：${providerLabel} 无法访问 ${modelLabel}，请检查设置里的 Provider 与模型是否匹配后重试。`,
        code: 'llm_request_failed',
      }
    }

    return {
      display: `大模型请求失败：${message || '请稍后重试，或切换模型后再试。'}`,
      code: 'llm_request_failed',
    }
  }

  if (code.startsWith('llm_invalid_response')) {
    return {
      display: '大模型返回了无法解析的结果，建议重试；如果持续出现，可缩短任务描述或切换模型。',
      code: 'llm_invalid_response',
    }
  }

  switch (code) {
    case 'llm_not_configured':
      return { display: '未配置大模型（LLM）API Key，请先在设置中配置后重试。', code }
    case 'no_questions_generated':
      return { display: '没有生成可用题目，可能约束过多或被判题筛掉；建议简化任务描述或降低难度后重试。', code }
    case 'Task ended unexpectedly':
      return { display: '任务意外终止，请重试。', code }
    case 'network_error':
      return { display: '网络异常或后端未启动，请检查后重试。', code }
    default:
      return { display: code }
  }
}
