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

function openDeal(url) {
  window.open(url, "_blank", "noopener");
}

async function resolvePipedrive(id) {
  try {
    const response = await fetch(`/api/v1/proposals/${id}/pipedrive/check`);
    if (!response.ok) return { message: await errorMessage(response) };
    const result = await response.json();
    if (result.status === "disabled") return {};
    if (result.status === "unavailable") return { message: result.message };

    if (result.status === "existing" && result.existing_deal) {
      const deal = result.existing_deal;
      if (window.confirm(`Já existe um negócio no Pipedrive com o nome:\n\n${deal.title}\n\nDeseja visualizar antes de criar outro?`)) {
        openDeal(deal.url);
      }
      if (window.confirm("Deseja criar um negócio mesmo assim?")) return { createPipedrive: true };
      return {};
    }
    if (result.status === "not_found" && window.confirm("Deseja criar um negócio no Pipedrive para esta proposta?")) {
      return { createPipedrive: true };
    }
    return {};
  } catch (_) {
    return { message: "Não foi possível consultar o Pipedrive. Nenhum negócio será criado e o PDF será gerado normalmente." };
  }
}

async function downloadPdf(id, params, pipedrive = {}) {
  const endpoint = pipedrive.createPipedrive
    ? `/api/v1/proposals/${id}/pipedrive/pdf?${params.toString()}`
    : `/api/v1/proposals/${id}/pdf?${params.toString()}`;
  const response = await fetch(endpoint, { method: pipedrive.createPipedrive ? "POST" : "GET" });
  if (!response.ok) throw new Error(await errorMessage(response));
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
  const dealUrl = response.headers.get("X-Pipedrive-Deal-Url");
  if (dealUrl) openDeal(dealUrl);
  const notice = [pipedrive.message, response.headers.get("X-Pipedrive-Message")].filter(Boolean).join(" ");
  showMessage(`${notice ? `${notice} ` : ""}Proposta ${id} gerada. O download foi iniciado.`, notice ? "warning" : "success");
  proposalNumber.select();
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
    const pipedrive = await resolvePipedrive(id);
    await downloadPdf(id, params, pipedrive);
  } catch (error) {
    showMessage(error.message || "Não foi possível gerar a proposta.", "error");
  } finally {
    setLoading(false);
  }
});
