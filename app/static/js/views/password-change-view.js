// 강제 비밀번호 변경 흐름에 연결되어 보안 갱신 화면을 제어한다.
export class PasswordChangeView {
  // 변경 폼과 로그아웃 동작을 상위 흐름에 연결한다.
  constructor({ root, form, currentPassword, newPassword, confirmPassword, error, submit, logout }) {
    this.root = root;
    this.form = form;
    this.currentPassword = currentPassword;
    this.newPassword = newPassword;
    this.confirmPassword = confirmPassword;
    this.error = error;
    this.submit = submit;
    this.logout = logout;
    this.submitHandler = null;
    this.logoutHandler = null;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.newPassword.value !== this.confirmPassword.value) {
        this.showError("새 비밀번호가 일치하지 않습니다.");
        this.confirmPassword.focus();
        return;
      }
      if (this.submitHandler) {
        this.submitHandler(this.currentPassword.value, this.newPassword.value);
      }
    });
    this.logout.addEventListener("click", () => {
      if (this.logoutHandler) this.logoutHandler();
    });
  }

  // 비밀번호 변경 요청을 처리할 핸들러를 등록한다.
  onSubmit(handler) {
    this.submitHandler = handler;
  }

  // 강제 변경 화면의 로그아웃 핸들러를 등록한다.
  onLogout(handler) {
    this.logoutHandler = handler;
  }

  // 변경 화면을 열고 현재 비밀번호 입력에 초점을 둔다.
  show() {
    this.root.hidden = false;
    this.currentPassword.focus();
  }

  // 변경 화면을 닫고 민감한 입력값을 지운다.
  hide() {
    this.root.hidden = true;
    this.form.reset();
    this.error.textContent = "";
  }

  // 변경 요청 중 입력과 이탈 동작을 잠근다.
  setBusy(isBusy) {
    this.currentPassword.disabled = isBusy;
    this.newPassword.disabled = isBusy;
    this.confirmPassword.disabled = isBusy;
    this.submit.disabled = isBusy;
    this.logout.disabled = isBusy;
    this.submit.textContent = isBusy ? "변경 중" : "비밀번호 변경";
  }

  // 비밀번호 변경 오류를 화면에 표시한다.
  showError(message) {
    this.error.textContent = message;
  }
}
