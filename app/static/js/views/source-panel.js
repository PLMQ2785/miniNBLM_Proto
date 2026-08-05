import { formatPage } from "../formatters.js";

export class SourcePanel {
  constructor({ root, title, pageLabel, content, closeButton, mobileToggle }) {
    this.root = root;
    this.title = title;
    this.pageLabel = pageLabel;
    this.content = content;
    this.closeButton = closeButton;
    this.mobileToggle = mobileToggle;
    this.closeHandler = null;
    this.currentUrl = null;

    this.closeButton.addEventListener("click", () => this.closeHandler?.());
    this.mobileToggle.addEventListener("click", () => this.root.classList.add("is-mobile-open"));
  }

  onClose(handler) {
    this.closeHandler = handler;
  }

  render(source, pdfUrl, documentTitle = "") {
    this.mobileToggle.hidden = !source;
    if (!source) {
      this.currentUrl = null;
      this.content.replaceChildren();
      this.title.textContent = "출처";
      this.pageLabel.textContent = "";
      const empty = document.createElement("p");
      empty.className = "source-empty-state";
      empty.textContent = "선택된 출처가 없습니다.";
      this.content.append(empty);
      this.root.classList.remove("has-source", "is-mobile-open");
      return;
    }

    this.title.textContent = documentTitle || "출처";
    this.pageLabel.textContent = formatPage(source.page);

    if (this.currentUrl === pdfUrl) return;
    this.currentUrl = pdfUrl;
    this.content.replaceChildren();

    const iframe = document.createElement("iframe");
    iframe.className = "pdf-frame";
    iframe.src = pdfUrl;
    iframe.title = `${documentTitle || "문서"} ${formatPage(source.page)}`;

    const fallback = document.createElement("a");
    fallback.className = "pdf-open-link";
    fallback.href = pdfUrl;
    fallback.target = "_blank";
    fallback.rel = "noopener noreferrer";
    fallback.textContent = "새 탭에서 PDF 열기";

    this.content.append(iframe, fallback);
    this.root.classList.add("has-source");
  }

  openMobile() {
    this.root.classList.add("is-mobile-open");
    this.root.dispatchEvent(new CustomEvent("panelvisibilitychange", { bubbles: true }));
  }

  closeMobile() {
    this.root.classList.remove("is-mobile-open");
    this.root.dispatchEvent(new CustomEvent("panelvisibilitychange", { bubbles: true }));
  }
}
