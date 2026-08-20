import { formatPage } from "../formatters.js";

// 채팅 출처 선택에 연결되어 원문 PDF 패널을 렌더링한다.
export class SourcePanel {
  // 출처 패널 요소와 데스크톱·모바일 닫기 동작을 연결한다.
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

  // 출처 닫기 요청을 처리할 상위 핸들러를 등록한다.
  onClose(handler) {
    this.closeHandler = handler;
  }

  // 선택한 출처의 문서 제목과 PDF를 패널에 표시한다.
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

    // 주변 UI만 바뀔 때는 PDF iframe을 다시 불러오지 않는다.
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

  // 모바일 출처 서랍을 열고 가시성 변경을 알린다.
  openMobile() {
    this.root.classList.add("is-mobile-open");
    this.root.dispatchEvent(new CustomEvent("panelvisibilitychange", { bubbles: true }));
  }

  // 모바일 출처 서랍을 닫고 가시성 변경을 알린다.
  closeMobile() {
    this.root.classList.remove("is-mobile-open");
    this.root.dispatchEvent(new CustomEvent("panelvisibilitychange", { bubbles: true }));
  }
}
