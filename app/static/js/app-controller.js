import { getConversation, upsertChatSession, upsertDocument } from "./state.js";

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const ACTIVE_STATUSES = new Set(["uploaded", "processing"]);

// 작업공간의 상태 전이와 API·화면 서비스를 조정하는 진입점이다.
export class AppController {
  // 공유 상태와 화면 이벤트를 연결해 사용자 동작을 컨트롤러로 모은다.
  constructor({ state, apiClient, pollingService, documentPanel, chatPanel, sourcePanel, notificationView }) {
    this.state = state;
    this.apiClient = apiClient;
    this.pollingService = pollingService;
    this.documentPanel = documentPanel;
    this.chatPanel = chatPanel;
    this.sourcePanel = sourcePanel;
    this.notificationView = notificationView;

    this.documentPanel.onUpload((files) => this.uploadDocuments(files));
    this.documentPanel.onDelete((documentId) => this.deleteDocument(documentId));
    this.documentPanel.onRefresh(() => this.loadDocuments({ announceSuccess: true }));
    this.chatPanel.onSubmit((question) => this.submitQuestion(question));
    this.chatPanel.onRetry((messageIndex) => this.retryQuestion(messageIndex));
    this.chatPanel.onSessionSelect((sessionId) => {
      if (sessionId) this.selectChatSession(Number(sessionId));
      else this.startNewConversation();
    });
    this.chatPanel.onNewSession(() => this.startNewConversation());
    this.chatPanel.onDeleteSession(() => this.deleteConversation(this.state.activeSessionId));
    this.chatPanel.onLoadOlder(() => this.loadOlderMessages());
    this.chatPanel.onSourceSelect((messageIndex, sourceIndex) => {
      const source = getConversation(this.state)[messageIndex]?.sources?.[sourceIndex];
      if (source) this.selectSource(source);
    });
    this.sourcePanel.onClose(() => this.sourcePanel.closeMobile());

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.pollingService.pause();
      else this.pollingService.resume();
    });
  }

  // 초기 화면에 필요한 상태를 서로 막지 않도록 함께 불러온다.
  async start() {
    await Promise.allSettled([
      this.checkHealth(),
      this.loadDocuments(),
      this.loadChatSessions(),
    ]);
  }

  // 대화 목록을 불러오고 사용할 세션 또는 새 대화를 선택한다.
  async loadChatSessions() {
    this.state.isLoadingSessions = true;
    this.render();
    try {
      this.state.chatSessions = await this.apiClient.listChatSessions();
      const activeSession = this.state.chatSessions.find(
        (session) => session.session_id === this.state.activeSessionId,
      ) || this.state.chatSessions[0];
      if (activeSession) {
        await this.selectChatSession(activeSession.session_id);
      } else {
        this.startNewConversation({ focus: false });
      }
    } catch (error) {
      this.notificationView.showError(error.message, {
        actionLabel: "대화 다시 불러오기",
        onAction: () => this.loadChatSessions(),
      });
    } finally {
      this.state.isLoadingSessions = false;
      this.render();
    }
  }

  // 선택한 대화로 상태를 전환하고 서버 이력을 채운다.
  async selectChatSession(sessionId) {
    if (!sessionId || this.state.isGenerating) return;
    this.state.activeSessionId = sessionId;
    this.state.isLoadingConversation = true;
    this.state.isLoadingOlderMessages = false;
    this.state.hasOlderMessages = false;
    this.state.conversation = [];
    this.clearSelectedSource();
    this.render();
    try {
      // 조회 중 다른 대화를 선택했다면 오래된 응답을 버린다.
      const session = await this.apiClient.getChatSession(sessionId);
      if (this.state.activeSessionId !== sessionId) return;
      this.state.chatSessions = upsertChatSession(this.state.chatSessions, session);
      this.state.conversation = session.messages.map((message) => this.toConversationMessage(message));
      this.state.hasOlderMessages = session.has_more;
    } catch (error) {
      const sessionWasRemoved = error.status === 404;
      if (error.status === 404) {
        this.state.chatSessions = this.state.chatSessions.filter(
          (session) => session.session_id !== sessionId,
        );
        this.state.activeSessionId = null;
      }
      this.notificationView.showError(error.message, {
        actionLabel: "대화 다시 불러오기",
        onAction: () => (
          sessionWasRemoved ? this.loadChatSessions() : this.selectChatSession(sessionId)
        ),
      });
    } finally {
      this.state.isLoadingConversation = false;
      this.render();
    }
  }

  // 저장된 세션 선택을 해제하고 빈 대화 작성 상태로 전환한다.
  startNewConversation({ focus = true } = {}) {
    if (this.state.isGenerating) return;
    this.state.activeSessionId = null;
    this.state.conversation = [];
    this.state.isLoadingConversation = false;
    this.state.hasOlderMessages = false;
    this.clearSelectedSource();
    this.render();
    if (focus) this.chatPanel.focusComposer();
  }

  // 서버와 로컬 목록에서 대화를 지운 뒤 다음 대화를 선택한다.
  async deleteConversation(sessionId, { skipConfirmation = false } = {}) {
    if (sessionId === null || this.state.isGenerating || this.state.deletingSessionId !== null) return;
    const session = this.state.chatSessions.find((item) => item.session_id === sessionId);
    if (!skipConfirmation
        && !window.confirm(`“${session?.title || "이 대화"}” 이력을 삭제할까요?`)) return;

    this.state.deletingSessionId = sessionId;
    this.render();
    try {
      await this.apiClient.deleteChatSession(sessionId);
      this.state.chatSessions = this.state.chatSessions.filter(
        (item) => item.session_id !== sessionId,
      );
      this.state.activeSessionId = null;
      this.state.conversation = [];
      this.state.hasOlderMessages = false;
      this.clearSelectedSource();
      const [nextSession] = this.state.chatSessions;
      if (nextSession) await this.selectChatSession(nextSession.session_id);
      else this.render();
      this.notificationView.showStatus("대화 이력을 삭제했습니다.");
    } catch (error) {
      this.notificationView.showError(error.message, {
        actionLabel: "삭제 재시도",
        onAction: () => this.deleteConversation(sessionId, { skipConfirmation: true }),
      });
    } finally {
      this.state.deletingSessionId = null;
      this.render();
    }
  }

  // 대화 전환이나 문서 삭제 때 출처 선택을 함께 해제한다.
  clearSelectedSource() {
    this.state.selectedSource = null;
    this.sourcePanel.closeMobile();
  }

  // 서버 메시지를 화면 대화가 사용하는 필드 형태로 바꾼다.
  toConversationMessage(message) {
    return {
      messageId: message.message_id,
      role: message.role,
      content: message.content,
      sources: message.sources || [],
    };
  }

  // 현재 대화 앞에 이전 메시지를 붙이고 스크롤 위치를 보존한다.
  async loadOlderMessages() {
    const sessionId = this.state.activeSessionId;
    const oldestMessageId = this.state.conversation[0]?.messageId;
    if (sessionId === null || !oldestMessageId || !this.state.hasOlderMessages
        || this.state.isLoadingOlderMessages) return;

    const scrollPosition = this.chatPanel.captureScrollPosition();
    this.state.isLoadingOlderMessages = true;
    this.render();
    try {
      const session = await this.apiClient.getChatSession(sessionId, { beforeId: oldestMessageId });
      this.state.conversation = [
        ...session.messages.map((message) => this.toConversationMessage(message)),
        ...this.state.conversation,
      ];
      this.state.hasOlderMessages = session.has_more;
    } catch (error) {
      this.notificationView.showError(error.message, {
        actionLabel: "다시 시도",
        onAction: () => this.loadOlderMessages(),
      });
    } finally {
      this.state.isLoadingOlderMessages = false;
      this.render();
      this.chatPanel.restoreScrollPosition(scrollPosition);
    }
  }

  // API 연결 상태를 작업공간 상태 표시에 반영한다.
  async checkHealth() {
    const status = document.querySelector("#service-status");
    try {
      await this.apiClient.health();
      status.textContent = "API 연결됨";
      status.dataset.state = "ready";
    } catch (error) {
      status.textContent = "API 연결 실패";
      status.dataset.state = "error";
    }
  }

  // 문서 목록을 갱신하고 처리 중 문서의 폴링을 맞춘다.
  async loadDocuments({ announceSuccess = false } = {}) {
    this.state.isLoadingDocuments = true;
    this.state.documentLoadError = null;
    this.render();
    try {
      this.state.documents = await this.apiClient.listDocuments();
      if (this.state.selectedSource && !this.state.documents.some(
        (documentSummary) => documentSummary.document_id === this.state.selectedSource.document_id,
      )) {
        this.state.selectedSource = null;
        this.sourcePanel.closeMobile();
      }
      this.syncPolling();
      if (announceSuccess) this.notificationView.showStatus("문서 목록을 새로고침했습니다.");
    } catch (error) {
      this.state.documentLoadError = error.message;
    } finally {
      this.state.isLoadingDocuments = false;
      this.render();
      if (this.state.documentLoadError) this.documentPanel.focusLoadError();
    }
  }

  // 업로드 가능한 PDF를 순서대로 전송해 진행률과 부분 실패를 구분한다.
  async uploadDocuments(files) {
    if (this.state.isUploading) return;

    const failures = [];
    const uploadableFiles = [];
    for (const file of Array.from(files)) {
      if (!this.isPdf(file)) {
        failures.push({ file, reason: "PDF 파일이 아닙니다." });
      } else if (file.size > MAX_UPLOAD_BYTES) {
        failures.push({ file, reason: "50MB를 초과합니다." });
      } else {
        uploadableFiles.push(file);
      }
    }
    this.documentPanel.clearFileInput();

    if (uploadableFiles.length === 0) {
      this.showUploadFailures(0, failures);
      return;
    }

    // 진행률과 부분 실패를 분명히 보여 주도록 파일을 순서대로 전송한다.
    let uploadedCount = 0;
    const retryableFiles = [];
    this.state.isUploading = true;
    this.state.uploadProgress = { current: 1, total: uploadableFiles.length };
    try {
      for (const [index, file] of uploadableFiles.entries()) {
        this.state.uploadProgress = { current: index + 1, total: uploadableFiles.length };
        this.render();
        try {
          const result = await this.apiClient.uploadDocument(file);
          const documentSummary = await this.apiClient.getDocument(result.document_id);
          this.state.documents = upsertDocument(this.state.documents, documentSummary);
          this.startPolling(documentSummary.document_id);
          uploadedCount += 1;
        } catch (error) {
          failures.push({ file, reason: error.message });
          retryableFiles.push(file);
        }
      }
    } finally {
      this.state.isUploading = false;
      this.state.uploadProgress = null;
      this.render();
    }

    if (failures.length > 0) {
      this.showUploadFailures(uploadedCount, failures, retryableFiles);
    } else {
      this.notificationView.showStatus(
        uploadedCount === 1 ? "PDF를 업로드했습니다." : `PDF ${uploadedCount}개를 업로드했습니다.`,
      );
    }
  }

  // 업로드 결과를 요약하고 전송 실패 파일에만 재시도를 제공한다.
  showUploadFailures(uploadedCount, failures, retryableFiles = []) {
    const preview = failures.slice(0, 2).map(
      ({ file, reason }) => `${file.name}: ${reason}`,
    ).join(" / ");
    const remainder = failures.length > 2 ? ` 외 ${failures.length - 2}개` : "";
    const prefix = uploadedCount > 0 ? `${uploadedCount}개 업로드 완료. ` : "";
    this.notificationView.showError(`${prefix}${failures.length}개 실패: ${preview}${remainder}`, {
      actionLabel: retryableFiles.length > 0 ? "실패 항목 재시도" : null,
      onAction: retryableFiles.length > 0 ? () => this.uploadDocuments(retryableFiles) : null,
    });
  }

  // 처리 중이 아닌 문서와 연결된 출처 상태를 함께 정리한다.
  async deleteDocument(documentId, { skipConfirmation = false } = {}) {
    const documentSummary = this.state.documents.find(
      (document) => document.document_id === documentId,
    );
    if (!documentSummary || this.state.deletingDocumentId !== null) return;
    if (ACTIVE_STATUSES.has(documentSummary.status)) {
      this.notificationView.showError("인덱싱이 끝난 후 문서를 삭제할 수 있습니다.");
      return;
    }
    if (!skipConfirmation
        && !window.confirm(`“${documentSummary.title}” 문서와 인덱싱 데이터를 모두 삭제할까요?`)) return;

    this.state.deletingDocumentId = documentId;
    this.render();
    try {
      await this.apiClient.deleteDocument(documentId);
      this.pollingService.stop(documentId);
      this.state.documents = this.state.documents.filter(
        (document) => document.document_id !== documentId,
      );
      this.state.conversation = this.state.conversation.map((message) => ({
        ...message,
        sources: message.sources?.map((source) => (
          source.document_id === documentId ? { ...source, available: false } : source
        )) || [],
      }));

      if (this.state.selectedSource?.document_id === documentId) {
        this.clearSelectedSource();
      }
      this.notificationView.showStatus(`${documentSummary.title} 문서를 삭제했습니다.`);
    } catch (error) {
      this.notificationView.showError(error.message, {
        actionLabel: "삭제 재시도",
        onAction: () => this.deleteDocument(documentId, { skipConfirmation: true }),
      });
    } finally {
      this.state.deletingDocumentId = null;
      this.render();
    }
  }

  // 질문을 대화에 추가하고 스트리밍 답변 생성을 시작한다.
  async submitQuestion(question) {
    if (!this.hasIndexedDocuments() || this.state.isGenerating || this.state.isLoadingConversation) return;

    const messages = [...getConversation(this.state), { role: "user", content: question, sources: [] }];
    this.chatPanel.clearInput();
    await this.generateAnswer(question, messages);
  }

  // 실패한 답변을 제외한 대화 맥락으로 같은 질문을 다시 보낸다.
  async retryQuestion(messageIndex) {
    const conversation = getConversation(this.state);
    const failedMessage = conversation[messageIndex];
    if (!this.hasIndexedDocuments() || this.state.isGenerating
        || failedMessage?.status !== "error" || !failedMessage.retryQuestion) return;

    const messages = conversation.filter((_, index) => index !== messageIndex);
    await this.generateAnswer(failedMessage.retryQuestion, messages);
  }

  // SSE 이벤트가 도착하는 동안 하나의 임시 답변을 계속 갱신한다.
  // SSE 세션·본문·교정·출처 이벤트를 작업공간 상태에 순서대로 반영한다.
  async generateAnswer(question, messages) {
    const originalSessionId = this.state.activeSessionId;
    const streamingMessage = {
      role: "assistant",
      content: "",
      sources: [],
      status: "streaming",
    };
    this.state.conversation = [...messages, streamingMessage];
    this.state.isGenerating = true;
    this.render();

    let focusMessageIndex = null;

    try {
      const result = await this.apiClient.streamQuestion(
        question,
        originalSessionId,
        (event, data) => {
          if (event === "session" || event === "done") {
            const session = event === "done" ? data.session : data;
            if (session) {
              this.state.activeSessionId = session.session_id;
              this.state.chatSessions = upsertChatSession(this.state.chatSessions, session);
              this.render();
            }
          } else if (event === "delta") {
            streamingMessage.content += data.text || "";
            this.chatPanel.updateStreamingMessage(
              this.state.conversation.length - 1,
              streamingMessage.content,
            );
          } else if (event === "revision") {
            // 교정 이벤트는 앞서 받은 전체 본문을 대체하는 최종 값이다.
            streamingMessage.content = data.text || "";
            this.chatPanel.updateStreamingMessage(
              this.state.conversation.length - 1,
              streamingMessage.content,
            );
          } else if (event === "sources") {
            streamingMessage.sources = data;
          }
        },
      );
      streamingMessage.content = result.answer;
      streamingMessage.sources = result.sources;
      delete streamingMessage.status;
      focusMessageIndex = this.state.conversation.length - 1;
    } catch (error) {
      // 새 스트림 실패로 빈 서버 세션이 생겼다면 로컬 선택에서 제거한다.
      if (originalSessionId === null && this.state.activeSessionId !== null) {
        const failedSessionId = this.state.activeSessionId;
        this.state.chatSessions = this.state.chatSessions.filter(
          (session) => session.session_id !== failedSessionId,
        );
        this.state.activeSessionId = null;
      }
      const nextMessages = [
        ...messages,
        {
          role: "assistant",
          content: error.message,
          sources: [],
          status: "error",
          retryQuestion: question,
        },
      ];
      this.state.conversation = nextMessages;
      focusMessageIndex = nextMessages.length - 1;
    } finally {
      this.state.isGenerating = false;
      this.render();
      if (focusMessageIndex !== null) this.chatPanel.focusMessage(focusMessageIndex);
    }
  }

  // 답변 출처를 선택하고 좁은 화면에서는 출처 패널을 연다.
  selectSource(source) {
    if (source.available === false) {
      this.notificationView.showError("삭제된 문서의 원본은 열 수 없습니다.");
      return;
    }
    this.state.selectedSource = source;
    this.render();
    if (window.matchMedia("(max-width: 900px)").matches) this.sourcePanel.openMobile();
  }

  // 문서가 최종 상태가 되거나 조회가 실패할 때까지 폴링한다.
  startPolling(documentId) {
    // 콜백이 false를 반환하면 이 문서의 반복 조회가 끝난다.
    this.pollingService.start(documentId, async (id) => {
      try {
        const documentSummary = await this.apiClient.getDocument(id);
        this.state.documents = upsertDocument(this.state.documents, documentSummary);
        this.render();
        if (!ACTIVE_STATUSES.has(documentSummary.status)) {
          if (documentSummary.status === "indexed") {
            this.notificationView.showStatus(`${documentSummary.title} 인덱싱을 완료했습니다.`);
          } else if (documentSummary.status === "failed") {
            this.notificationView.showError(
              documentSummary.error_message || "문서 처리에 실패했습니다.",
              { focus: false },
            );
          }
          return false;
        }
        return true;
      } catch (error) {
        this.notificationView.showError(error.message, {
          actionLabel: "목록 새로고침",
          onAction: () => this.loadDocuments({ announceSuccess: true }),
          focus: false,
        });
        return false;
      }
    });
  }

  // 현재 처리 중인 문서에만 폴링 작업이 남도록 다시 구성한다.
  syncPolling() {
    this.pollingService.stopAll();
    for (const documentSummary of this.state.documents) {
      if (ACTIVE_STATUSES.has(documentSummary.status)) {
        this.startPolling(documentSummary.document_id);
      }
    }
  }

  // 공유 상태를 각 화면에 전달해 작업공간 표시를 일관되게 갱신한다.
  render() {
    const conversation = getConversation(this.state);
    this.documentPanel.render(this.state.documents, {
      isLoading: this.state.isLoadingDocuments,
      loadError: this.state.documentLoadError,
      isUploading: this.state.isUploading,
      uploadProgress: this.state.uploadProgress,
      deletingDocumentId: this.state.deletingDocumentId,
    });
    this.chatPanel.render(this.state.documents, conversation, {
      isGenerating: this.state.isGenerating,
      isLoading: this.state.isLoadingDocuments,
      chatSessions: this.state.chatSessions,
      activeSessionId: this.state.activeSessionId,
      isLoadingSessions: this.state.isLoadingSessions,
      isLoadingConversation: this.state.isLoadingConversation,
      isLoadingOlderMessages: this.state.isLoadingOlderMessages,
      hasOlderMessages: this.state.hasOlderMessages,
      deletingSessionId: this.state.deletingSessionId,
    });

    const source = this.state.selectedSource;
    const pdfUrl = source
      ? this.apiClient.getPdfUrl(source.document_id, source.page)
      : null;
    this.sourcePanel.render(source, pdfUrl, source?.document_title || "");
  }

  // MIME 형식이나 확장자로 업로드 파일의 PDF 여부를 판정한다.
  isPdf(file) {
    return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  }

  // 질문 전송에 사용할 수 있는 인덱싱 완료 문서가 있는지 확인한다.
  hasIndexedDocuments() {
    return this.state.documents.some((document) => document.status === "indexed");
  }
}
