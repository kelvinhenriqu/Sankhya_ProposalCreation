const form = document.querySelector("#proposal-form");
const proposalNumber = document.querySelector("#proposal-number");
const responsible = document.querySelector("#responsible");
const clientEmail = document.querySelector("#client-email");
const submitButton = document.querySelector("#submit-button");
const buttonLabel = submitButton.querySelector(".button-label");
const downloadExistingButton = document.querySelector("#download-existing-button");
const downloadExistingLabel = downloadExistingButton.querySelector(".download-existing-label");
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

function setLoading(loading, action = "generate") {
  submitButton.disabled = loading;
  downloadExistingButton.disabled = loading;
  submitButton.classList.toggle("loading", loading);
  if (!loading) {
    buttonLabel.textContent = "Gerar e baixar PDF";
  } else if (action === "generate") {
    buttonLabel.textContent = "Gerando proposta...";
  } else if (action === "decision") {
    buttonLabel.textContent = "Aguardando sua decis\u00e3o...";
  }
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

function askPipedrive(question) {
  return new Promise((resolve) => {
    const text = document.createElement("span");
    text.textContent = `${question} `;
    const yes = document.createElement("button");
    yes.type = "button";
    yes.textContent = "Sim";
    const no = document.createElement("button");
    no.type = "button";
    no.textContent = "N\u00e3o";
    const actions = document.createElement("div");
    actions.className = "choice-actions";
    actions.append(yes, no);

    const answer = (value) => {
      clearMessage();
      resolve(value);
    };
    yes.addEventListener("click", () => answer(true));
    no.addEventListener("click", () => answer(false));
    message.replaceChildren(text, actions);
    message.className = "message";
    message.hidden = false;
  });
}

async function resolvePipedrive(id) {
  try {
    buttonLabel.textContent = "Consultando Pipedrive...";
    const response = await fetch(`/api/v1/proposals/${id}/pipedrive/check`);
    if (!response.ok) return { message: await errorMessage(response) };
    const result = await response.json();
    if (result.status === "disabled") return {};
    if (result.status === "unavailable") return { message: result.message };
    if (result.status === "existing" && result.existing_deal) {
      buttonLabel.textContent = "Aguardando sua decis\u00e3o...";
      const createPipedrive = await askPipedrive(
        `J\u00e1 existe um neg\u00f3cio no Pipedrive: ${result.existing_deal.title}. Deseja criar outro mesmo assim?`,
      );
      return {
        createPipedrive,
        message: createPipedrive ? "Um novo neg\u00f3cio ser\u00e1 criado no Pipedrive." : "Nenhum novo neg\u00f3cio ser\u00e1 criado.",
      };
    }
    if (result.status === "not_found") {
      buttonLabel.textContent = "Aguardando sua decis\u00e3o...";
      const createPipedrive = await askPipedrive(
        "Nenhum neg\u00f3cio foi encontrado no Pipedrive. Deseja criar um e anexar o PDF?",
      );
      return {
        createPipedrive,
        message: createPipedrive ? "Um novo neg\u00f3cio ser\u00e1 criado no Pipedrive." : "O PDF ser\u00e1 gerado sem criar um neg\u00f3cio.",
      };
    }
    return {};
  } catch (_) {
    return { message: "N\u00e3o foi poss\u00edvel consultar o Pipedrive. O PDF ser\u00e1 gerado normalmente." };
  }
}

async function downloadPdf(id, params, pipedrive = {}) {
  const endpoint = pipedrive.createPipedrive
    ? `/api/v1/proposals/${id}/pipedrive/pdf?${params.toString()}`
    : `/api/v1/proposals/${id}/pdf?${params.toString()}`;
  buttonLabel.textContent = pipedrive.createPipedrive
    ? "Consultando Sankhya, gerando e enviando ao Pipedrive..."
    : "Consultando Sankhya e gerando PDF...";
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

  setLoading(true, "decision");
  try {
    const usePipedrive = await askPipedrive("Comunicar-se com Pipedrive?");
    const pipedrive = usePipedrive
      ? await resolvePipedrive(id)
      : { message: "O PDF ser\u00e1 gerado sem consultar o Pipedrive." };
    await downloadPdf(id, params, pipedrive);
  } catch (error) {
    showMessage(error.message || "Não foi possível gerar a proposta.", "error");
  } finally {
    setLoading(false);
  }
});

downloadExistingButton.addEventListener("click", async () => {
  clearMessage();
  const id = Number(proposalNumber.value);
  if (!Number.isInteger(id) || id <= 0) {
    proposalNumber.setAttribute("aria-invalid", "true");
    showMessage("Informe um n\u00famero de proposta v\u00e1lido.", "error");
    proposalNumber.focus();
    return;
  }
  proposalNumber.removeAttribute("aria-invalid");

  setLoading(true, "decision");
  downloadExistingLabel.textContent = "Aguardando sua decis\u00e3o...";
  try {
    const usePipedrive = await askPipedrive("Deseja buscar o PDF salvo no Pipedrive?");
    if (!usePipedrive) {
      showMessage("Busca no Pipedrive cancelada.", "success");
      return;
    }
    downloadExistingLabel.textContent = "Buscando PDF no Pipedrive...";
    const response = await fetch(`/api/v1/proposals/${id}/pipedrive/download`);
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
    showMessage(`PDF da proposta ${id} baixado do Pipedrive.`, "success");
    proposalNumber.select();
  } catch (error) {
    showMessage(error.message || "N\u00e3o foi poss\u00edvel baixar o PDF do Pipedrive.", "error");
  } finally {
    downloadExistingLabel.textContent = "Baixar PDF salvo no Pipedrive";
    setLoading(false);
  }
});
