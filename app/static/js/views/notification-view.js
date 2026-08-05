export class NotificationView {
  constructor(root) {
    this.root = root;
    this.timerId = null;
  }

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

  showStatus(message) {
    this.show(message, "status", 3500);
  }

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

  clear() {
    window.clearTimeout(this.timerId);
    this.root.replaceChildren();
  }
}
