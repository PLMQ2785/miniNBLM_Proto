// 문서별 반복 조회를 겹침 없이 예약하고 화면 비활성화를 제어한다.
export class PollingService {
  // 조회 간격과 문서별 예약 작업을 초기화한다.
  constructor(intervalMs = 2000) {
    this.intervalMs = intervalMs;
    this.tasks = new Map();
    this.paused = false;
  }

  // 같은 문서의 기존 작업을 교체하고 콜백이 false일 때 반복을 끝낸다.
  start(documentId, callback) {
    this.stop(documentId);
    const task = { timerId: null, callback };
    this.tasks.set(documentId, task);

    // 느린 요청이 겹치지 않도록 콜백이 끝난 뒤 다음 조회를 예약한다.
    // 일시정지와 콜백 결과를 반영해 다음 조회 또는 종료를 결정한다.
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

  // 지정 문서의 예약을 취소하고 작업 목록에서 제거한다.
  stop(documentId) {
    const task = this.tasks.get(documentId);
    if (!task) return;
    if (task.timerId != null) window.clearTimeout(task.timerId);
    this.tasks.delete(documentId);
  }

  // 화면 전환이나 종료 시 모든 문서 폴링을 해제한다.
  stopAll() {
    for (const documentId of this.tasks.keys()) this.stop(documentId);
  }

  // 숨겨진 화면에서는 요청 없이 예약만 유지한다.
  pause() {
    this.paused = true;
  }

  // 화면이 다시 보이면 다음 예약부터 조회를 재개한다.
  resume() {
    this.paused = false;
  }
}
