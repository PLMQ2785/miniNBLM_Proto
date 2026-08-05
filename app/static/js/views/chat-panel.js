import { formatPage } from "../formatters.js";

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

  render(documents, messages, { isGenerating, isLoading }) {
    const indexedCount = documents.filter((document) => document.status === "indexed").length;
    const processingCount = documents.filter(
      (document) => document.status === "uploaded" || document.status === "processing",
    ).length;
    const failedCount = documents.filter((document) => document.status === "failed").length;
    const isReady = indexedCount > 0;

    this.title.textContent = "전체 문서 검색";
    this.status.textContent = this.workspaceStatus({
      indexedCount,
      processingCount,
      failedCount,
      isLoading,
    });
    this.input.disabled = !isReady || isGenerating;
    this.sendButton.disabled = !isReady || isGenerating;
    this.input.placeholder = isReady
      ? "업로드한 전체 자료에 대해 질문하세요"
      : "검색 가능한 PDF를 추가하세요";
    this.sendButton.textContent = isGenerating ? "답변 생성 중" : "질문 보내기";
    this.messageList.replaceChildren();

    if (messages.length === 0) {
      let emptyMessage = "업로드한 전체 자료에 대해 질문하세요.";
      if (isLoading && documents.length === 0) {
        emptyMessage = "문서를 불러오는 중입니다.";
      } else if (!isReady && processingCount > 0) {
        emptyMessage = "문서를 인덱싱하고 있습니다.";
      } else if (!isReady) {
        emptyMessage = documents.length === 0
          ? "PDF를 추가하면 전체 자료를 대상으로 질문할 수 있습니다."
          : "검색 가능한 문서가 없습니다. 실패 상태를 확인하거나 PDF를 추가하세요.";
      }
      this.messageList.append(this.emptyState(emptyMessage));
    } else {
      messages.forEach((message, messageIndex) => {
        this.messageList.append(this.messageElement(message, messageIndex, isGenerating));
      });
    }
    if (isGenerating) this.messageList.append(this.pendingElement());
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  workspaceStatus({ indexedCount, processingCount, failedCount, isLoading }) {
    const parts = [];
    if (indexedCount > 0) parts.push(`검색 가능 ${indexedCount}개`);
    if (processingCount > 0) parts.push(`처리 중 ${processingCount}개`);
    if (failedCount > 0) parts.push(`실패 ${failedCount}개`);
    if (parts.length === 0) return isLoading ? "목록 확인 중" : "등록된 문서 없음";
    return parts.join(" · ");
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
