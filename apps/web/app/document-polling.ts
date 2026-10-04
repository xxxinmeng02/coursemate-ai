type PollingOptions<T> = {
  fetch: (signal: AbortSignal) => Promise<T>;
  onData: (data: T) => boolean;
  onError: (reason: unknown) => void;
  onTimeout: () => void;
};

// The deadline belongs to a polling session, rather than to each fetched result.
export function createDocumentPolling<T>(options: PollingOptions<T>) {
  let running = false;
  let generation = 0;
  let request: AbortController | null = null;
  let nextTick: ReturnType<typeof setTimeout> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;

  function stop() {
    running = false;
    generation++;
    clearTimeout(nextTick);
    clearTimeout(deadline);
    request?.abort();
  }

  async function tick() {
    if (!running || request) return;
    const currentGeneration = generation;
    const controller = new AbortController();
    request = controller;
    try {
      const data = await options.fetch(controller.signal);
      if (running && currentGeneration === generation && !options.onData(data)) stop();
    } catch (reason) {
      if (running && currentGeneration === generation) {
        stop();
        options.onError(reason);
      }
    } finally {
      request = null;
      if (running) nextTick = setTimeout(() => void tick(), 3000);
    }
  }

  function restart(immediate = false) {
    running = true;
    generation++;
    clearTimeout(nextTick);
    clearTimeout(deadline);
    deadline = setTimeout(() => {
      stop();
      options.onTimeout();
    }, 120000);
    // An existing request must finish before the next one can begin.
    if (!request) nextTick = setTimeout(() => void tick(), immediate ? 0 : 3000);
  }

  return { restart, stop };
}
