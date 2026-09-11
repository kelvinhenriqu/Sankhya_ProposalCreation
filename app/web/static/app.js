const form = document.querySelector("#proposal-form");
const proposalNumber = document.querySelector("#proposal-number");
const responsible = document.querySelector("#responsible");
const clientEmail = document.querySelector("#client-email");
const submitButton = document.querySelector("#submit-button");
const buttonLabel = submitButton.querySelector(".button-label");
const message = document.querySelector("#message");

const STORAGE_RESPONSIBLE = "proposal.responsible";
const STORAGE_EMAIL = "proposal.clientEmail";

responsible.value = localStorage.getItem(STORAGE_RESPONSIBLE) || "";
clientEmail.value = localStorage.getItem(STORAGE_EMAIL) || "";

function showMessage(text, type) {
  message.textContent = text;
  message.className = `message ${type}`;
  message.hidden = false;
}

function clearMessage() {
  message.hidden = true;
  message.textContent = "";
  message.className = "message";
}

function setLoading(loading) {
  submitButton.disabled = loading;
  submitButton.classList.toggle("loading", loading);
  buttonLabel.textContent = loading ? "Gerando proposta…" : "Gerar e baixar PDF";
  form.setAttribute("aria-busy", String(loading));
}

function filenameFromHeader(header) {
  if (!header) return "proposta.pdf";
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (_) {
      return utf8Match[1];
    }
  }
  const basicMatch = header.match(/filename="([^"]+)"/i);
  return basicMatch ? basicMatch[1] : "proposta.pdf";
}

async function errorMessage(response) {
  try {
    const payload = await response.json();
    const correlation = payload.correlation_id ? ` Código: ${payload.correlation_id}` : "";
    return `${payload.mensagem || "Não foi possível gerar a proposta."}${correlation}`;
  } catch (_) {
    return `Não foi possível gerar a proposta (HTTP ${response.status}).`;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage();

  const id = Number(proposalNumber.value);
  if (!Number.isInteger(id) || id <= 0) {
    proposalNumber.setAttribute("aria-invalid", "true");
    showMessage("Informe um número de proposta válido.", "error");
    proposalNumber.focus();
    return;
  }
  proposalNumber.removeAttribute("aria-invalid");

  if (!responsible.value.trim()) {
    responsible.setAttribute("aria-invalid", "true");
    showMessage("Informe o responsável pela proposta.", "error");
    responsible.focus();
    return;
  }
  responsible.removeAttribute("aria-invalid");

  if (!clientEmail.value.trim()) {
    clientEmail.setAttribute("aria-invalid", "true");
    showMessage("Informe o e-mail do cliente.", "error");
    clientEmail.focus();
    return;
  }
  clientEmail.removeAttribute("aria-invalid");

  localStorage.setItem(STORAGE_RESPONSIBLE, responsible.value.trim());
  localStorage.setItem(STORAGE_EMAIL, clientEmail.value.trim());
  const params = new URLSearchParams({
    responsavel: responsible.value.trim(),
    email_cliente: clientEmail.value.trim(),
  });

  setLoading(true);
  try {
    const response = await fetch(`/api/v1/proposals/${id}/pdf?${params.toString()}`);
    if (!response.ok) {
      throw new Error(await errorMessage(response));
    }
    const blob = await response.blob();
    const filename = filenameFromHeader(response.headers.get("Content-Disposition"));
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    showMessage(`Proposta ${id} gerada. O download foi iniciado.`, "success");
    proposalNumber.select();
  } catch (error) {
    showMessage(error.message || "Não foi possível gerar a proposta.", "error");
  } finally {
    setLoading(false);
  }
});
