import { getConversation, upsertChatSession, upsertDocument } from "./state.js";

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const ACTIVE_STATUSES = new Set(["uploaded", "processing"]);

export class AppController {
  constructor({ state, apiClient, pollingService, documentPanel, chatPanel, sourcePanel, notificationView }) {
    this.state = state;
    this.apiClient = apiClient;
    this.pollingService = pollingService;
    this.documentPanel = documentPanel;
    this.chatPanel = chatPanel;
    this.sourcePanel = sourcePanel;
    this.notificationView = notificationView;

    this.documentPanel.onUpload((file) => this.uploadDocument(file));
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

  async start() {
    await Promise.allSettled([
      this.checkHealth(),
      this.loadDocuments(),
      this.loadChatSessions(),
    ]);
  }

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

  clearSelectedSource() {
    this.state.selectedSource = null;
    this.sourcePanel.closeMobile();
  }

  toConversationMessage(message) {
    return {
      messageId: message.message_id,
      role: message.role,
      content: message.content,
      sources: message.sources || [],
    };
  }

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

  async uploadDocument(file) {
    if (!this.isPdf(file)) {
      this.notificationView.showError("PDF 파일만 추가할 수 있습니다.");
      this.documentPanel.clearFileInput();
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      this.notificationView.showError("PDF 파일은 50MB 이하여야 합니다.");
      this.documentPanel.clearFileInput();
      return;
    }

    this.state.isUploading = true;
    this.render();
    try {
      const result = await this.apiClient.uploadDocument(file);
      const documentSummary = await this.apiClient.getDocument(result.document_id);
      this.state.documents = upsertDocument(this.state.documents, documentSummary);
      this.startPolling(documentSummary.document_id);
      this.notificationView.showStatus("PDF를 업로드했습니다.");
    } catch (error) {
      this.notificationView.showError(error.message, {
        actionLabel: "업로드 재시도",
        onAction: () => this.uploadDocument(file),
      });
    } finally {
      this.state.isUploading = false;
      this.documentPanel.clearFileInput();
      this.render();
    }
  }

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

  async submitQuestion(question) {
    if (!this.hasIndexedDocuments() || this.state.isGenerating || this.state.isLoadingConversation) return;

    const messages = [...getConversation(this.state), { role: "user", content: question, sources: [] }];
    this.chatPanel.clearInput();
    await this.generateAnswer(question, messages);
  }

  async retryQuestion(messageIndex) {
    const conversation = getConversation(this.state);
    const failedMessage = conversation[messageIndex];
    if (!this.hasIndexedDocuments() || this.state.isGenerating
        || failedMessage?.status !== "error" || !failedMessage.retryQuestion) return;

    const messages = conversation.filter((_, index) => index !== messageIndex);
    await this.generateAnswer(failedMessage.retryQuestion, messages);
  }

  async generateAnswer(question, messages) {
    this.state.conversation = messages;
    this.state.isGenerating = true;
    this.render();

    let focusMessageIndex = null;

    try {
      const result = await this.apiClient.sendQuestion(question, this.state.activeSessionId);
      this.state.activeSessionId = result.session.session_id;
      this.state.chatSessions = upsertChatSession(this.state.chatSessions, result.session);
      const nextMessages = [
        ...messages,
        { role: "assistant", content: result.answer, sources: result.sources },
      ];
      this.state.conversation = nextMessages;
      focusMessageIndex = nextMessages.length - 1;
    } catch (error) {
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

  selectSource(source) {
    if (source.available === false) {
      this.notificationView.showError("삭제된 문서의 원본은 열 수 없습니다.");
      return;
    }
    this.state.selectedSource = source;
    this.render();
    if (window.matchMedia("(max-width: 900px)").matches) this.sourcePanel.openMobile();
  }

  startPolling(documentId) {
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

  syncPolling() {
    this.pollingService.stopAll();
    for (const documentSummary of this.state.documents) {
      if (ACTIVE_STATUSES.has(documentSummary.status)) {
        this.startPolling(documentSummary.document_id);
      }
    }
  }

  render() {
    const conversation = getConversation(this.state);
    this.documentPanel.render(this.state.documents, {
      isLoading: this.state.isLoadingDocuments,
      loadError: this.state.documentLoadError,
      isUploading: this.state.isUploading,
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

  isPdf(file) {
    return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  }

  hasIndexedDocuments() {
    return this.state.documents.some((document) => document.status === "indexed");
  }
}
