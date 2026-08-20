import { formatDate, formatStatus } from "../formatters.js";

// 작업공간 문서 상태에 연결되어 업로드 목록과 작업 버튼을 렌더링한다.
export class DocumentPanel {
  // 문서 패널 요소와 선택·업로드·새로고침·삭제 이벤트를 연결한다.
  constructor({ listRoot, uploadForm, fileInput, uploadStatus, refreshButton }) {
    this.listRoot = listRoot;
    this.uploadForm = uploadForm;
    this.fileInput = fileInput;
    this.uploadStatus = uploadStatus;
    this.refreshButton = refreshButton;
    this.uploadHandler = null;
    this.deleteHandler = null;
    this.refreshHandler = null;
    this.selectHandler = null;

    this.fileInput.addEventListener("change", () => {
      const files = Array.from(this.fileInput.files || []);
      if (files.length > 0 && this.uploadHandler) this.uploadHandler(files);
    });
    this.uploadForm.addEventListener("submit", (event) => event.preventDefault());
    this.refreshButton.addEventListener("click", () => {
      if (this.refreshHandler) this.refreshHandler();
    });
    // 목록을 매번 다시 그리므로 행 동작은 컨테이너에서 위임받는다.
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
      const selectButton = event.target.closest("[data-select-document-id]");
      if (selectButton && this.selectHandler) {
        this.selectHandler(Number(selectButton.dataset.selectDocumentId));
      }
    });
  }

  // 선택한 파일을 전달할 업로드 핸들러를 등록한다.
  onUpload(handler) {
    this.uploadHandler = handler;
  }

  // 문서 삭제 요청을 처리할 핸들러를 등록한다.
  onDelete(handler) {
    this.deleteHandler = handler;
  }

  // 목록 새로고침 요청을 처리할 핸들러를 등록한다.
  onRefresh(handler) {
    this.refreshHandler = handler;
  }

  // 질의 대상으로 고른 문서를 처리할 핸들러를 등록한다.
  onSelect(handler) {
    this.selectHandler = handler;
  }

  // 재선택할 수 있도록 브라우저 파일 선택값을 비운다.
  clearFileInput() {
    this.fileInput.value = "";
  }

  // 로딩·오류·업로드 상태에 맞춰 문서 목록을 다시 그린다.
  render(documents, {
    isLoading,
    loadError,
    isUploading,
    uploadProgress,
    deletingDocumentId,
    selectedDocumentId,
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
      row.dataset.selected = String(documentSummary.document_id === selectedDocumentId);

      const item = document.createElement("button");
      const isSelectable = documentSummary.status === "indexed";
      const isSelected = documentSummary.document_id === selectedDocumentId;
      item.type = "button";
      item.className = "document-item";
      item.dataset.selectDocumentId = documentSummary.document_id;
      item.dataset.status = documentSummary.status;
      item.dataset.selected = String(isSelected);
      item.disabled = !isSelectable;
      item.setAttribute("aria-pressed", String(isSelected));
      item.setAttribute("aria-label", `${documentSummary.title} 질의 대상으로 선택`);

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
      if (documentSummary.error_message) {
        item.title = documentSummary.error_message;
      } else if (!isSelectable) {
        item.title = "인덱싱 완료 후 질의 대상으로 선택할 수 있습니다.";
      }

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

  // 문서 목록의 빈 상태 안내 요소를 만든다.
  emptyState(message) {
    const element = document.createElement("p");
    element.className = "panel-empty-state";
    element.textContent = message;
    return element;
  }

  // 새로고침 동작이 포함된 목록 오류 요소를 만든다.
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

  // 목록 로드 오류로 키보드 초점을 옮긴다.
  focusLoadError() {
    this.listRoot.querySelector(".panel-error-state")?.focus();
  }
}
