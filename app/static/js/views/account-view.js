export class AccountView {
  constructor({
    root,
    username,
    close,
    passwordForm,
    currentPassword,
    newPassword,
    confirmPassword,
    passwordMessage,
    passwordSubmit,
    deleteForm,
    deletePassword,
    deleteConfirmation,
    deleteError,
    deleteSubmit,
  }) {
    this.root = root;
    this.username = username;
    this.close = close;
    this.passwordForm = passwordForm;
    this.currentPassword = currentPassword;
    this.newPassword = newPassword;
    this.confirmPassword = confirmPassword;
    this.passwordMessage = passwordMessage;
    this.passwordSubmit = passwordSubmit;
    this.deleteForm = deleteForm;
    this.deletePassword = deletePassword;
    this.deleteConfirmation = deleteConfirmation;
    this.deleteError = deleteError;
    this.deleteSubmit = deleteSubmit;
    this.passwordHandler = null;
    this.deleteHandler = null;
    this.closeHandler = null;

    this.passwordForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.newPassword.value !== this.confirmPassword.value) {
        this.showPasswordMessage("새 비밀번호가 일치하지 않습니다.", true);
        this.confirmPassword.focus();
        return;
      }
      this.passwordHandler?.(this.currentPassword.value, this.newPassword.value);
    });
    this.deleteForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.deleteConfirmation.value.trim().toLowerCase() !== this.username.textContent) {
        this.showDeleteError("사용자명이 일치하지 않습니다.");
        this.deleteConfirmation.focus();
        return;
      }
      if (!window.confirm("계정과 모든 문서 및 대화 이력을 삭제할까요? 이 작업은 되돌릴 수 없습니다.")) {
        return;
      }
      this.deleteHandler?.(this.deletePassword.value, this.deleteConfirmation.value);
    });
    this.close.addEventListener("click", () => this.closeHandler?.());
  }

  onPasswordChange(handler) {
    this.passwordHandler = handler;
  }

  onDelete(handler) {
    this.deleteHandler = handler;
  }

  onClose(handler) {
    this.closeHandler = handler;
  }

  show(user) {
    this.username.textContent = user.username;
    this.root.hidden = false;
    this.currentPassword.focus();
  }

  hide() {
    this.root.hidden = true;
    this.passwordForm.reset();
    this.deleteForm.reset();
    this.showPasswordMessage("");
    this.showDeleteError("");
  }

  setPasswordBusy(isBusy) {
    for (const element of [
      this.currentPassword,
      this.newPassword,
      this.confirmPassword,
      this.passwordSubmit,
    ]) element.disabled = isBusy;
    this.passwordSubmit.textContent = isBusy ? "변경 중" : "비밀번호 변경";
  }

  setDeleteBusy(isBusy) {
    for (const element of [
      this.deletePassword,
      this.deleteConfirmation,
      this.deleteSubmit,
    ]) element.disabled = isBusy;
    this.deleteSubmit.textContent = isBusy ? "탈퇴 처리 중" : "회원탈퇴";
  }

  showPasswordMessage(message, isError = false) {
    this.passwordMessage.textContent = message;
    this.passwordMessage.dataset.state = isError ? "error" : "success";
  }

  showDeleteError(message) {
    this.deleteError.textContent = message;
  }

  resetPasswordForm() {
    this.passwordForm.reset();
    this.currentPassword.focus();
  }
}
