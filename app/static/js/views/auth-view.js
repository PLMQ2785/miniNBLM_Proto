// 메인 인증 흐름에 연결되어 로그인·회원가입 화면을 제어한다.
export class AuthView {
  // 인증 폼 요소와 전환·제출 이벤트를 연결한다.
  constructor({ root, form, title, username, password, error, submit, loginTab, registerTab }) {
    this.root = root;
    this.form = form;
    this.title = title;
    this.username = username;
    this.password = password;
    this.error = error;
    this.submit = submit;
    this.loginTab = loginTab;
    this.registerTab = registerTab;
    this.mode = "login";
    this.submitHandler = null;

    this.loginTab.addEventListener("click", () => this.setMode("login"));
    this.registerTab.addEventListener("click", () => this.setMode("register"));
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.submitHandler) {
        this.submitHandler(this.mode, this.username.value, this.password.value);
      }
    });
  }

  // 인증 요청을 처리할 상위 핸들러를 등록한다.
  onSubmit(handler) {
    this.submitHandler = handler;
  }

  // 로그인과 회원가입 모드에 맞춰 폼 상태를 바꾼다.
  setMode(mode) {
    this.mode = mode;
    const isLogin = mode === "login";
    this.loginTab.setAttribute("aria-selected", String(isLogin));
    this.registerTab.setAttribute("aria-selected", String(!isLogin));
    this.title.textContent = isLogin ? "로그인" : "회원가입";
    this.submit.textContent = isLogin ? "로그인" : "계정 만들기";
    this.password.autocomplete = isLogin ? "current-password" : "new-password";
    this.password.minLength = isLogin ? 1 : 8;
    this.error.textContent = "";
    this.password.value = "";
    this.username.focus();
  }

  // 인증 화면을 열고 사용자명 입력으로 초점을 옮긴다.
  show() {
    this.root.hidden = false;
    this.username.focus();
  }

  // 인증 화면을 닫고 입력 및 오류 상태를 초기화한다.
  hide() {
    this.root.hidden = true;
    this.form.reset();
    this.error.textContent = "";
  }

  // 인증 요청 중 폼 조작을 잠그고 진행 문구를 표시한다.
  setBusy(isBusy) {
    this.username.disabled = isBusy;
    this.password.disabled = isBusy;
    this.submit.disabled = isBusy;
    this.loginTab.disabled = isBusy;
    this.registerTab.disabled = isBusy;
    if (isBusy) this.submit.textContent = this.mode === "login" ? "로그인 중" : "생성 중";
    else this.submit.textContent = this.mode === "login" ? "로그인" : "계정 만들기";
  }

  // 인증 실패 메시지를 화면에 표시한다.
  showError(message) {
    this.error.textContent = message;
  }
}
