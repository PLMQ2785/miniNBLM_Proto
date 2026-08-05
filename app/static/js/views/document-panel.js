import { formatDate, formatStatus } from "../formatters.js";

export class DocumentPanel {
  constructor({ listRoot, uploadForm, fileInput, uploadStatus, refreshButton }) {
    this.listRoot = listRoot;
    this.uploadForm = uploadForm;
    this.fileInput = fileInput;
    this.uploadStatus = uploadStatus;
    this.refreshButton = refreshButton;
    this.uploadHandler = null;
    this.deleteHandler = null;
    this.refreshHandler = null;

    this.fileInput.addEventListener("change", () => {
      const files = Array.from(this.fileInput.files || []);
      if (files.length > 0 && this.uploadHandler) this.uploadHandler(files);
    });
    this.uploadForm.addEventListener("submit", (event) => event.preventDefault());
    this.refreshButton.addEventListener("click", () => {
      if (this.refreshHandler) this.refreshHandler();
    });
    this.listRoot.addEventListener("click", (event) => {
      const refreshButton = event.target.closest("[data-refresh-documents]");
      if (refreshButton && this.refreshHandler) {
        this.refreshHandler();
        return;
      }
      const deleteButton = event.target.closest("[data-delete-document-id]");
      if (deleteButton && this.deleteHandler) {
        this.deleteHandler(Number(deleteButton.dataset.deleteDocumentId));
        return;
      }
    });
  }

  onUpload(handler) {
    this.uploadHandler = handler;
  }

  onDelete(handler) {
    this.deleteHandler = handler;
  }

  onRefresh(handler) {
    this.refreshHandler = handler;
  }

  clearFileInput() {
    this.fileInput.value = "";
  }

  render(documents, {
    isLoading,
    loadError,
    isUploading,
    uploadProgress,
    deletingDocumentId,
  }) {
    this.uploadStatus.textContent = isUploading && uploadProgress?.total > 1
      ? `업로드 중 ${uploadProgress.current}/${uploadProgress.total}`
      : (isUploading ? "업로드 중" : "");
    this.fileInput.disabled = isUploading;
    this.refreshButton.disabled = isLoading;
    this.refreshButton.dataset.loading = String(isLoading);
    this.listRoot.replaceChildren();

    if (isLoading) {
      this.listRoot.append(this.emptyState("문서를 불러오는 중입니다."));
      return;
    }
    if (loadError) {
      this.listRoot.append(this.errorState(loadError));
      return;
    }
    if (documents.length === 0) {
      this.listRoot.append(this.emptyState("등록된 문서가 없습니다."));
      return;
    }

    for (const documentSummary of documents) {
      const row = document.createElement("div");
      row.className = "document-row";

      const item = document.createElement("div");
      item.className = "document-item";
      item.dataset.documentId = documentSummary.document_id;
      item.dataset.status = documentSummary.status;

      const title = document.createElement("span");
      title.className = "document-title";
      title.textContent = documentSummary.title;

      const meta = document.createElement("span");
      meta.className = "document-meta";

      const status = document.createElement("span");
      status.className = `status-badge status-${documentSummary.status}`;
      status.textContent = formatStatus(documentSummary.status);

      const date = document.createElement("time");
      date.dateTime = documentSummary.created_at;
      date.textContent = formatDate(documentSummary.created_at);

      meta.append(status, date);
      item.append(title, meta);
      if (documentSummary.error_message) item.title = documentSummary.error_message;

      const deleteButton = document.createElement("button");
      const isActive = ["uploaded", "processing"].includes(documentSummary.status);
      const isDeleting = deletingDocumentId === documentSummary.document_id;
      deleteButton.type = "button";
      deleteButton.className = "document-delete-button";
      deleteButton.dataset.deleteDocumentId = documentSummary.document_id;
      deleteButton.disabled = isActive || isDeleting;
      deleteButton.textContent = isDeleting ? "삭제 중" : "삭제";
      deleteButton.setAttribute("aria-label", `${documentSummary.title} 삭제`);
      if (isActive) deleteButton.title = "인덱싱 완료 후 삭제할 수 있습니다.";

      row.append(item, deleteButton);
      this.listRoot.append(row);
    }
  }

  emptyState(message) {
    const element = document.createElement("p");
    element.className = "panel-empty-state";
    element.textContent = message;
    return element;
  }

  errorState(message) {
    const element = document.createElement("div");
    element.className = "panel-error-state";
    element.tabIndex = -1;

    const text = document.createElement("p");
    text.textContent = message;

    const retryButton = document.createElement("button");
    retryButton.type = "button";
    retryButton.dataset.refreshDocuments = "true";
    retryButton.textContent = "다시 시도";
    element.append(text, retryButton);
    return element;
  }

  focusLoadError() {
    this.listRoot.querySelector(".panel-error-state")?.focus();
  }
}
