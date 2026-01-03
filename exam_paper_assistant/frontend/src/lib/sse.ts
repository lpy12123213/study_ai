export async function* readSseData(
  response: Response,
  options?: { signal?: AbortSignal },
): AsyncGenerator<string, void, void> {
  const { signal } = options ?? {};

  if (!response.body) {
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }

      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      while (true) {
        const idxNn = buffer.indexOf("\n\n");
        const idxCrLf = buffer.indexOf("\r\n\r\n");
        const boundary =
          idxNn === -1
            ? idxCrLf
            : idxCrLf === -1
              ? idxNn
              : Math.min(idxNn, idxCrLf);

        if (boundary === -1) break;

        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + (boundary === idxCrLf ? 4 : 2));

        const lines = rawEvent.split(/\r?\n/);
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          yield line.slice("data:".length).trimStart();
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

