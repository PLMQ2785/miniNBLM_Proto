export class AuthView {
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

  onSubmit(handler) {
    this.submitHandler = handler;
  }

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

  show() {
    this.root.hidden = false;
    this.username.focus();
  }

  hide() {
    this.root.hidden = true;
    this.form.reset();
    this.error.textContent = "";
  }

  setBusy(isBusy) {
    this.username.disabled = isBusy;
    this.password.disabled = isBusy;
    this.submit.disabled = isBusy;
    this.loginTab.disabled = isBusy;
    this.registerTab.disabled = isBusy;
    if (isBusy) this.submit.textContent = this.mode === "login" ? "로그인 중" : "생성 중";
    else this.submit.textContent = this.mode === "login" ? "로그인" : "계정 만들기";
  }

  showError(message) {
    this.error.textContent = message;
  }
}
