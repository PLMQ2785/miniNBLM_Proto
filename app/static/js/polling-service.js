export class PollingService {
  constructor(intervalMs = 2000) {
    this.intervalMs = intervalMs;
    this.tasks = new Map();
    this.paused = false;
  }

  start(documentId, callback) {
    this.stop(documentId);
    const task = { timerId: null, callback };
    this.tasks.set(documentId, task);

    const tick = async () => {
      if (!this.tasks.has(documentId)) return;
      if (this.paused) {
        task.timerId = window.setTimeout(tick, this.intervalMs);
        return;
      }

      let shouldContinue = true;
      try {
        shouldContinue = (await callback(documentId)) !== false;
      } finally {
        if (shouldContinue && this.tasks.has(documentId)) {
          task.timerId = window.setTimeout(tick, this.intervalMs);
        } else {
          this.stop(documentId);
        }
      }
    };

    task.timerId = window.setTimeout(tick, this.intervalMs);
  }

  stop(documentId) {
    const task = this.tasks.get(documentId);
    if (!task) return;
    if (task.timerId != null) window.clearTimeout(task.timerId);
    this.tasks.delete(documentId);
  }

  stopAll() {
    for (const documentId of this.tasks.keys()) this.stop(documentId);
  }

  pause() {
    this.paused = true;
  }

  resume() {
    this.paused = false;
  }
}
