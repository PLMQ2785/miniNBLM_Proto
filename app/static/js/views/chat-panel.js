import { formatPage, formatStatus } from "../formatters.js";

// 작업공간 상태에 연결되어 대화 이력과 질문·답변 메시지를 렌더링한다.
export class ChatPanel {
  // 대화 패널 요소와 작성·출처·세션 이벤트를 연결한다.
  constructor({
    status,
    messageList,
    form,
    input,
    sendButton,
    sessionSelect,
    newSessionButton,
    deleteSessionButton,
  }) {
    this.status = status;
    this.messageList = messageList;
    this.form = form;
    this.input = input;
    this.sendButton = sendButton;
    this.sessionSelect = sessionSelect;
    this.newSessionButton = newSessionButton;
    this.deleteSessionButton = deleteSessionButton;
    this.submitHandler = null;
    this.sourceHandler = null;
    this.retryHandler = null;
    this.sessionSelectHandler = null;
    this.newSessionHandler = null;
    this.deleteSessionHandler = null;
    this.loadOlderHandler = null;

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
    // 메시지를 다시 그려도 동작하도록 목록 컨테이너에서 클릭을 위임받는다.
    this.messageList.addEventListener("click", (event) => {
      const loadOlderButton = event.target.closest("[data-load-older-messages]");
      if (loadOlderButton && this.loadOlderHandler) {
        this.loadOlderHandler();
        return;
      }
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
    this.sessionSelect.addEventListener("change", () => {
      if (this.sessionSelectHandler) this.sessionSelectHandler(this.sessionSelect.value);
    });
    this.newSessionButton.addEventListener("click", () => this.newSessionHandler?.());
    this.deleteSessionButton.addEventListener("click", () => this.deleteSessionHandler?.());
  }

  // 질문 전송을 처리할 상위 핸들러를 등록한다.
  onSubmit(handler) {
    this.submitHandler = handler;
  }

  // 답변 출처 선택을 처리할 핸들러를 등록한다.
  onSourceSelect(handler) {
    this.sourceHandler = handler;
  }

  // 실패한 질문의 재시도 핸들러를 등록한다.
  onRetry(handler) {
    this.retryHandler = handler;
  }

  // 대화 이력 선택을 처리할 핸들러를 등록한다.
  onSessionSelect(handler) {
    this.sessionSelectHandler = handler;
  }

  // 새 대화 요청을 처리할 핸들러를 등록한다.
  onNewSession(handler) {
    this.newSessionHandler = handler;
  }

  // 현재 대화 삭제 요청을 처리할 핸들러를 등록한다.
  onDeleteSession(handler) {
    this.deleteSessionHandler = handler;
  }

  // 이전 메시지 조회 요청을 처리할 핸들러를 등록한다.
  onLoadOlder(handler) {
    this.loadOlderHandler = handler;
  }

  // 전송을 마친 질문 입력을 비운다.
  clearInput() {
    this.input.value = "";
  }

  // 다음 질문을 위해 작성 영역에 초점을 둔다.
  focusComposer() {
    this.input.focus();
  }

  // 문서와 대화 상태에 맞춰 작업공간 채팅을 다시 그린다.
  render(documents, messages, {
    isGenerating,
    isLoading,
    chatSessions,
    activeSessionId,
    isLoadingSessions,
    isLoadingConversation,
    isLoadingOlderMessages,
    hasOlderMessages,
    deletingSessionId,
    selectedDocumentId,
  }) {
    const indexedCount = documents.filter((document) => document.status === "indexed").length;
    const processingCount = documents.filter(
      (document) => document.status === "uploaded" || document.status === "processing",
    ).length;
    const failedCount = documents.filter((document) => document.status === "failed").length;
    const selectedDocument = documents.find(
      (document) => document.document_id === selectedDocumentId,
    ) || null;
    const isReady = selectedDocument ? selectedDocument.status === "indexed" : indexedCount > 0;

    this.status.textContent = this.workspaceStatus({
      indexedCount,
      processingCount,
      failedCount,
      isLoading,
      selectedDocument,
    });
    this.renderSessionControls(chatSessions, activeSessionId, {
      isGenerating,
      isLoadingSessions,
      isLoadingConversation,
      isLoadingOlderMessages,
      deletingSessionId,
    });
    this.input.placeholder = selectedDocument
      ? `${selectedDocument.title} 문서에 대해 질문하세요.`
      : "전체 문서에 대해 질문하세요.";
    this.input.disabled = !isReady || isGenerating || isLoadingConversation;
    this.sendButton.disabled = !isReady || isGenerating || isLoadingConversation;
    this.sendButton.textContent = isGenerating ? "답변 생성 중" : "질문 보내기";
    this.messageList.replaceChildren();

    if (isLoadingConversation) {
      this.messageList.append(this.emptyState("대화를 불러오는 중입니다."));
    } else if (messages.length === 0) {
      let emptyMessage = selectedDocument
        ? `“${selectedDocument.title}” 문서에 대해 질문하세요.`
        : "업로드한 전체 문서에 대해 질문하세요.";
      if (isLoading && documents.length === 0) {
        emptyMessage = "문서를 불러오는 중입니다.";
      } else if (indexedCount === 0 && processingCount > 0) {
        emptyMessage = "문서를 인덱싱하고 있습니다.";
      } else if (indexedCount === 0) {
        emptyMessage = documents.length === 0
          ? "PDF를 추가하면 문서별로 질문할 수 있습니다."
          : "검색 가능한 문서가 없습니다. 실패 상태를 확인하거나 PDF를 추가하세요.";
      }
      this.messageList.append(this.emptyState(emptyMessage));
    } else {
      if (hasOlderMessages) {
        this.messageList.append(this.loadOlderElement(isLoadingOlderMessages || isGenerating));
      }
      messages.forEach((message, messageIndex) => {
        this.messageList.append(this.messageElement(message, messageIndex, isGenerating));
      });
    }
    const hasStreamingMessage = messages.some((message) => message.status === "streaming");
    if (isGenerating && !hasStreamingMessage) this.messageList.append(this.pendingElement());
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  // 이전 메시지 삽입 전 현재 스크롤 기준점을 저장한다.
  captureScrollPosition() {
    return {
      height: this.messageList.scrollHeight,
      top: this.messageList.scrollTop,
    };
  }

  // 이전 메시지 삽입 뒤 사용자가 보던 위치를 복원한다.
  restoreScrollPosition({ height, top }) {
    this.messageList.scrollTop = top + this.messageList.scrollHeight - height;
  }

  // 대화 목록과 생성·삭제 버튼의 사용 가능 상태를 렌더링한다.
  renderSessionControls(chatSessions, activeSessionId, {
    isGenerating,
    isLoadingSessions,
    isLoadingConversation,
    isLoadingOlderMessages,
    deletingSessionId,
  }) {
    this.sessionSelect.replaceChildren();
    if (isLoadingSessions) {
      this.sessionSelect.append(new Option("대화 불러오는 중", ""));
    } else {
      const newConversation = new Option("새 대화", "", activeSessionId === null, activeSessionId === null);
      this.sessionSelect.append(newConversation);
      for (const session of chatSessions) {
        const selected = session.session_id === activeSessionId;
        this.sessionSelect.append(new Option(session.title, String(session.session_id), selected, selected));
      }
    }

    const controlsBusy = isGenerating || isLoadingSessions || isLoadingConversation
      || isLoadingOlderMessages || deletingSessionId !== null;
    this.sessionSelect.disabled = controlsBusy;
    this.newSessionButton.disabled = controlsBusy || activeSessionId === null;
    this.deleteSessionButton.disabled = controlsBusy || activeSessionId === null;
    this.deleteSessionButton.textContent = deletingSessionId === activeSessionId ? "삭제 중" : "삭제";
  }

  // 문서 처리 현황과 현재 전체·개별 질의 범위를 채팅 헤더 문구로 만든다.
  workspaceStatus({ indexedCount, processingCount, failedCount, isLoading, selectedDocument }) {
    if (selectedDocument) {
      return `질의 대상 · ${selectedDocument.title} · ${formatStatus(selectedDocument.status)}`;
    }
    const parts = [];
    if (indexedCount > 0) parts.push(`검색 가능 ${indexedCount}개`);
    if (processingCount > 0) parts.push(`처리 중 ${processingCount}개`);
    if (failedCount > 0) parts.push(`실패 ${failedCount}개`);
    if (parts.length === 0) return isLoading ? "목록 확인 중" : "등록된 문서 없음";
    return `${parts.join(" · ")} · 전체 문서 질의`;
  }

  // 역할·상태·출처를 포함한 대화 메시지 요소를 만든다.
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
    if (message.status === "streaming") {
      article.classList.add("message-streaming");
      article.setAttribute("aria-busy", "true");
    }

    const role = document.createElement("span");
    role.className = "message-role";
    role.textContent = message.role === "user"
      ? "나"
      : message.status === "error" ? "오류" : "Answer";

    const content = document.createElement("p");
    content.className = "message-content";
    content.textContent = message.content || (
      message.status === "streaming" ? "자료를 확인하고 있습니다." : ""
    );
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
        button.disabled = source.available === false;
        const label = `${source.document_title || "문서"} · ${formatPage(source.page)}`;
        button.textContent = label;
        button.title = source.available === false ? `${label} · 삭제된 문서` : label;
        sourceList.append(button);
      });
      article.append(sourceList);
    }
    return article;
  }

  // 스트리밍 중인 답변 내용을 기존 메시지에 반영한다.
  updateStreamingMessage(messageIndex, content) {
    const message = this.messageList.querySelector(`[data-message-index="${messageIndex}"]`);
    const contentElement = message?.querySelector(".message-content");
    if (!contentElement) return;
    contentElement.textContent = content || "자료를 확인하고 있습니다.";
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  // 응답 완료 또는 오류 메시지로 키보드 초점을 옮긴다.
  focusMessage(messageIndex) {
    const message = this.messageList.querySelector(`[data-message-index="${messageIndex}"]`);
    if (!message) return;
    message.focus({ preventScroll: true });
    message.scrollIntoView({ block: "nearest" });
  }

  // 답변 생성 중임을 알리는 대기 메시지를 만든다.
  pendingElement() {
    const element = document.createElement("div");
    element.className = "message message-assistant message-pending";
    element.setAttribute("role", "status");
    element.textContent = "자료를 확인하고 있습니다.";
    return element;
  }

  // 이전 메시지를 불러오는 버튼 영역을 만든다.
  loadOlderElement(isLoading) {
    const container = document.createElement("div");
    container.className = "load-older-messages";
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.loadOlderMessages = "true";
    button.disabled = isLoading;
    button.textContent = isLoading ? "불러오는 중" : "이전 메시지 보기";
    container.append(button);
    return container;
  }

  // 대화 목록의 빈 상태 안내 요소를 만든다.
  emptyState(message) {
    const element = document.createElement("div");
    element.className = "chat-empty-state";
    element.textContent = message;
    return element;
  }
}
