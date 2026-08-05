export class NotificationView {
  constructor(root) {
    this.root = root;
    this.timerId = null;
  }

  showError(message) {
    this.show(message, "error", 6000);
  }

  showStatus(message) {
    this.show(message, "status", 3500);
  }

  show(message, type, duration) {
    window.clearTimeout(this.timerId);
    this.root.replaceChildren();
    const notification = document.createElement("div");
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    this.root.append(notification);
    this.timerId = window.setTimeout(() => this.clear(), duration);
  }

  clear() {
    window.clearTimeout(this.timerId);
    this.root.replaceChildren();
  }
}
