export class PasswordChangeView {
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

  onSubmit(handler) {
    this.submitHandler = handler;
  }

  onLogout(handler) {
    this.logoutHandler = handler;
  }

  show() {
    this.root.hidden = false;
    this.currentPassword.focus();
  }

  hide() {
    this.root.hidden = true;
    this.form.reset();
    this.error.textContent = "";
  }

  setBusy(isBusy) {
    this.currentPassword.disabled = isBusy;
    this.newPassword.disabled = isBusy;
    this.confirmPassword.disabled = isBusy;
    this.submit.disabled = isBusy;
    this.logout.disabled = isBusy;
    this.submit.textContent = isBusy ? "변경 중" : "비밀번호 변경";
  }

  showError(message) {
    this.error.textContent = message;
  }
}
