// 전역 알림 영역에 오류와 상태 메시지를 렌더링한다.
export class NotificationView {
  // 알림 컨테이너와 자동 해제 타이머를 준비한다.
  constructor(root) {
    this.root = root;
    this.timerId = null;
  }

  // 복구 동작을 선택적으로 포함한 오류 알림을 표시한다.
  showError(message, {
    actionLabel = null,
    onAction = null,
    focus = true,
  } = {}) {
    this.show(message, "error", actionLabel ? 10000 : 6000, {
      actionLabel,
      onAction,
      focus,
    });
  }

  // 짧게 유지되는 일반 상태 알림을 표시한다.
  showStatus(message) {
    this.show(message, "status", 3500);
  }

  // 유형과 유지 시간에 따라 알림 요소를 구성한다.
  show(message, type, duration, { actionLabel = null, onAction = null, focus = false } = {}) {
    window.clearTimeout(this.timerId);
    this.root.replaceChildren();
    const notification = document.createElement("div");
    notification.className = `notification notification-${type}`;
    notification.tabIndex = -1;

    const text = document.createElement("p");
    text.textContent = message;
    notification.append(text);

    if (actionLabel && onAction) {
      const actionButton = document.createElement("button");
      actionButton.type = "button";
      actionButton.className = "notification-action";
      actionButton.textContent = actionLabel;
      actionButton.addEventListener("click", () => {
        this.clear();
        onAction();
      });
      notification.append(actionButton);
    }
    this.root.append(notification);
    if (focus) notification.focus();
    this.timerId = window.setTimeout(() => this.clear(), duration);
  }

  // 현재 알림과 예약된 자동 해제를 함께 제거한다.
  clear() {
    window.clearTimeout(this.timerId);
    this.root.replaceChildren();
  }
}
