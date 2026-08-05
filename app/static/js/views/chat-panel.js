import { formatPage, formatStatus } from "../formatters.js";

export class ChatPanel {
  constructor({ title, status, messageList, form, input, sendButton }) {
    this.title = title;
    this.status = status;
    this.messageList = messageList;
    this.form = form;
    this.input = input;
    this.sendButton = sendButton;
    this.submitHandler = null;
    this.sourceHandler = null;
    this.retryHandler = null;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      const question = this.input.value.trim();
      if (question && this.submitHandler) this.submitHandler(question);
    });
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        this.form.requestSubmit();
      }
    });
    this.messageList.addEventListener("click", (event) => {
      const retryButton = event.target.closest("[data-retry-message-index]");
      if (retryButton && this.retryHandler) {
        this.retryHandler(Number(retryButton.dataset.retryMessageIndex));
        return;
      }
      const button = event.target.closest("[data-source-index]");
      if (!button || !this.sourceHandler) return;
      const messageIndex = Number(button.dataset.messageIndex);
      const sourceIndex = Number(button.dataset.sourceIndex);
      this.sourceHandler(messageIndex, sourceIndex);
    });
  }

  onSubmit(handler) {
    this.submitHandler = handler;
  }

  onSourceSelect(handler) {
    this.sourceHandler = handler;
  }

  onRetry(handler) {
    this.retryHandler = handler;
  }

  clearInput() {
    this.input.value = "";
  }

  focusComposer() {
    this.input.focus();
  }

  render(documentSummary, messages, isGenerating) {
    const isReady = documentSummary?.status === "indexed";
    this.title.textContent = documentSummary?.title || "문서를 선택하세요";
    this.status.textContent = documentSummary ? formatStatus(documentSummary.status) : "";
    this.input.disabled = !isReady || isGenerating;
    this.sendButton.disabled = !isReady || isGenerating;
    this.sendButton.textContent = isGenerating ? "답변 생성 중" : "질문 보내기";
    this.messageList.replaceChildren();

    if (!documentSummary) {
      this.messageList.append(this.emptyState("질문할 문서를 선택하세요."));
      return;
    }
    if (!isReady) {
      const text = documentSummary.status === "failed"
        ? documentSummary.error_message || "문서 처리에 실패했습니다."
        : "문서를 인덱싱하고 있습니다.";
      this.messageList.append(this.emptyState(text));
      return;
    }
    if (messages.length === 0) {
      this.messageList.append(this.emptyState("아직 대화가 없습니다."));
    } else {
      messages.forEach((message, messageIndex) => {
        this.messageList.append(this.messageElement(message, messageIndex, isGenerating));
      });
    }
    if (isGenerating) this.messageList.append(this.pendingElement());
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  messageElement(message, messageIndex, isGenerating) {
    const article = document.createElement("article");
    article.className = `message message-${message.role}`;
    article.dataset.messageIndex = messageIndex;
    if (message.status === "error") {
      article.classList.add("message-error");
      article.setAttribute("role", "alert");
      article.tabIndex = -1;
    } else if (message.role === "assistant") {
      article.tabIndex = -1;
    }

    const role = document.createElement("span");
    role.className = "message-role";
    role.textContent = message.role === "user"
      ? "나"
      : message.status === "error" ? "오류" : "Tutor";

    const content = document.createElement("p");
    content.className = "message-content";
    content.textContent = message.content;
    article.append(role, content);

    if (message.status === "error" && message.retryQuestion) {
      const retryButton = document.createElement("button");
      retryButton.type = "button";
      retryButton.className = "message-retry-button";
      retryButton.dataset.retryMessageIndex = messageIndex;
      retryButton.disabled = isGenerating;
      retryButton.textContent = "질문 다시 시도";
      article.append(retryButton);
    }

    if (message.sources?.length) {
      const sourceList = document.createElement("div");
      sourceList.className = "message-sources";
      sourceList.setAttribute("aria-label", "답변 출처");
      message.sources.forEach((source, sourceIndex) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "source-reference";
        button.dataset.messageIndex = messageIndex;
        button.dataset.sourceIndex = sourceIndex;
        const label = `${source.document_title || "문서"} · ${formatPage(source.page)}`;
        button.textContent = label;
        button.title = label;
        sourceList.append(button);
      });
      article.append(sourceList);
    }
    return article;
  }

  focusMessage(messageIndex) {
    const message = this.messageList.querySelector(`[data-message-index="${messageIndex}"]`);
    if (!message) return;
    message.focus({ preventScroll: true });
    message.scrollIntoView({ block: "nearest" });
  }

  pendingElement() {
    const element = document.createElement("div");
    element.className = "message message-assistant message-pending";
    element.setAttribute("role", "status");
    element.textContent = "자료를 확인하고 있습니다.";
    return element;
  }

  emptyState(message) {
    const element = document.createElement("div");
    element.className = "chat-empty-state";
    element.textContent = message;
    return element;
  }
}
