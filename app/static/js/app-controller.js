import { getConversation, getSelectedDocument, upsertDocument } from "./state.js";

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
    this.documentPanel.onSelect((documentId) => this.selectDocument(documentId));
    this.documentPanel.onDelete((documentId) => this.deleteDocument(documentId));
    this.chatPanel.onSubmit((question) => this.submitQuestion(question));
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
    await Promise.allSettled([this.checkHealth(), this.loadDocuments()]);
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

  async loadDocuments() {
    this.state.isLoadingDocuments = true;
    this.render();
    try {
      this.state.documents = await this.apiClient.listDocuments();
      const selected = getSelectedDocument(this.state);
      if (!selected) {
        this.state.selectedDocumentId = this.state.documents.find(
          (documentSummary) => documentSummary.status === "indexed",
        )?.document_id ?? this.state.documents[0]?.document_id ?? null;
      }
      this.syncPolling();
    } catch (error) {
      this.notificationView.showError(error.message);
    } finally {
      this.state.isLoadingDocuments = false;
      this.render();
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
      this.state.selectedDocumentId = documentSummary.document_id;
      this.startPolling(documentSummary.document_id);
      this.notificationView.showStatus("PDF를 업로드했습니다.");
    } catch (error) {
      this.notificationView.showError(error.message);
    } finally {
      this.state.isUploading = false;
      this.documentPanel.clearFileInput();
      this.render();
    }
  }

  selectDocument(documentId) {
    this.state.selectedDocumentId = documentId;
    this.state.selectedSource = null;
    this.sourcePanel.closeMobile();
    this.render();
    const selected = getSelectedDocument(this.state);
    if (selected?.status === "indexed") this.chatPanel.focusComposer();
  }

  async deleteDocument(documentId) {
    const documentSummary = this.state.documents.find(
      (document) => document.document_id === documentId,
    );
    if (!documentSummary || this.state.deletingDocumentId !== null) return;
    if (ACTIVE_STATUSES.has(documentSummary.status)) {
      this.notificationView.showError("인덱싱이 끝난 후 문서를 삭제할 수 있습니다.");
      return;
    }
    if (!window.confirm(`“${documentSummary.title}” 문서와 관련 대화를 모두 삭제할까요?`)) return;

    this.state.deletingDocumentId = documentId;
    this.render();
    try {
      await this.apiClient.deleteDocument(documentId);
      this.pollingService.stop(documentId);
      this.state.documents = this.state.documents.filter(
        (document) => document.document_id !== documentId,
      );
      this.state.conversations.delete(documentId);

      if (this.state.selectedDocumentId === documentId) {
        this.state.selectedDocumentId = this.state.documents.find(
          (document) => document.status === "indexed",
        )?.document_id ?? this.state.documents[0]?.document_id ?? null;
        this.state.selectedSource = null;
        this.sourcePanel.closeMobile();
      }
      this.notificationView.showStatus(`${documentSummary.title} 문서를 삭제했습니다.`);
    } catch (error) {
      this.notificationView.showError(error.message);
    } finally {
      this.state.deletingDocumentId = null;
      this.render();
    }
  }

  async submitQuestion(question) {
    const selected = getSelectedDocument(this.state);
    if (!selected || selected.status !== "indexed" || this.state.isGenerating) return;

    const messages = [...getConversation(this.state), { role: "user", content: question, sources: [] }];
    this.state.conversations.set(selected.document_id, messages);
    this.state.isGenerating = true;
    this.chatPanel.clearInput();
    this.render();

    try {
      const result = await this.apiClient.sendQuestion(selected.document_id, question);
      this.state.conversations.set(selected.document_id, [
        ...messages,
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
    } catch (error) {
      this.notificationView.showError(error.message);
    } finally {
      this.state.isGenerating = false;
      this.render();
      this.chatPanel.focusComposer();
    }
  }

  selectSource(source) {
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
            this.notificationView.showError(documentSummary.error_message || "문서 처리에 실패했습니다.");
          }
          return false;
        }
        return true;
      } catch (error) {
        this.notificationView.showError(error.message);
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
    const selected = getSelectedDocument(this.state);
    const conversation = getConversation(this.state);
    this.documentPanel.render(this.state.documents, this.state.selectedDocumentId, {
      isLoading: this.state.isLoadingDocuments,
      isUploading: this.state.isUploading,
      deletingDocumentId: this.state.deletingDocumentId,
    });
    this.chatPanel.render(selected, conversation, this.state.isGenerating);

    const source = this.state.selectedSource;
    const pdfUrl = source
      ? this.apiClient.getPdfUrl(source.document_id, source.page)
      : null;
    this.sourcePanel.render(source, pdfUrl, selected?.title || "");
  }

  isPdf(file) {
    return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  }
}
