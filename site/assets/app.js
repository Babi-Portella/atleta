"use strict";
const button = document.querySelector("[data-copy]");
if (button) {
  button.addEventListener("click", async () => {
    const source = document.getElementById(button.dataset.copy);
    const status = document.getElementById("copy-status");
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(source.textContent);
      status.textContent = "JSON copiado.";
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(source);
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = "JSON selecionado. Use Ctrl+C ou a opção Copiar.";
    }
  });
}
