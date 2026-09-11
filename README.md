# Sankhya GetProposal

Além da consulta em JSON, a aplicação gera o PDF final com os templates locais da pasta `Templates`. Não há dependência de SharePoint, Word Online Business ou Adobe PDF Tools. A conversão usa uma instância oculta do Microsoft Word Desktop instalado no Windows; o merge é feito em Python.

Implementação Python/FastAPI do fluxo `PA_Sankhya_GetProposal`. Esta etapa consulta e normaliza a proposta, enriquece os itens com Homepage e PDF de descrição e devolve JSON. Ela não gera o PDF final.

## Configuração

1. Instale Python 3.11 ou superior.
2. Preencha `.env` com credenciais Sankhya novas ou rotacionadas.
3. Instale as dependências. Com `uv`:

```powershell
uv sync --extra dev
```

Ou com `venv`/pip:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Nunca versione `.env`. O arquivo `.env.example` documenta as variáveis necessárias sem conter secrets.

## Executar

No Windows, prefira o inicializador abaixo. Ele garante que a API use o Python do `.venv`, valida `pywin32` antes de iniciar e evita o erro de executar com outro interpretador:

```powershell
.\start.ps1
```

Alternativamente:

```powershell
uv run uvicorn app.main:app --reload
```

Com o ambiente virtual já ativo, também pode usar `uvicorn app.main:app --reload`.

Abra a interface no navegador:

```text
http://127.0.0.1:8000/
```

Digite o número da proposta, responsável e e-mail do cliente. Pressionar Enter consulta a Sankhya, gera o documento e inicia o download do PDF.

Consulta:

```http
GET /api/v1/proposals/{id_memoria}
```

Exemplo:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/proposals/123
```

A resposta contém `sucesso`, `mensagem` e `proposta`. Diferentemente do Power Automate, `proposta` é um objeto JSON, e não uma string contendo JSON.

## Gerar o PDF final

Para consultar a Sankhya e receber diretamente o PDF:

```http
GET /api/v1/proposals/{id_memoria}/pdf?responsavel=Nome&email_cliente=email@cliente.com
```

No PowerShell, use `-OutFile` para salvar o binário:

```powershell
Invoke-WebRequest `
  "http://127.0.0.1:8000/api/v1/proposals/123/pdf?responsavel=Nome&email_cliente=email@cliente.com" `
  -OutFile proposta.pdf
```

Também é possível gerar a partir do JSON já consultado:

```http
POST /api/v1/proposals/pdf
Content-Type: application/json
```

```json
{
  "proposta": {
    "Cabecalho": {},
    "Vendedor": "NOME DO VENDEDOR",
    "Itens": []
  },
  "responsavel": "Nome",
  "email_cliente": "email@cliente.com"
}
```

O retorno é `application/pdf` com `Content-Disposition: attachment`. A ordem é cabeçalho, itens, PDFs dos produtos presentes em `PdfBase64` e condições.

Arquivos usados:

- `Templates/Cabecalho.docx`;
- `Templates/Itens.docx`;
- `Templates/Condicoes.docx`;
- `Templates/Dados.xlsx` para telefone e email do vendedor.

`Templates/Produto.docx` não fazia parte do flow exportado e não é usado nesta versão.

## Testes

```powershell
uv run pytest
```

## Docker com LibreOffice headless

O host precisa apenas do Docker. O LibreOffice, o Python e as fontes livres são instalados dentro da imagem; os usuários finais não precisam instalar Word ou LibreOffice.

Preencha o `.env` local e execute:

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

Imagem publicada no GitHub Container Registry:

```text
ghcr.io/kelvinhenriqu/sankhya-proposal-creation:latest
```

Em um servidor que apenas consumirá a imagem:

```powershell
docker pull ghcr.io/kelvinhenriqu/sankhya-proposal-creation:latest
docker compose up -d
```

A interface fica em `http://localhost:8000/`. Para publicar em outra porta:

```powershell
$env:APP_PORT = "8080"
docker compose up --build -d
```

Os templates não são versionados e também não são incorporados na imagem Docker. Por padrão, o Compose monta a pasta local ignorada `./Templates` em `/app/Templates` como somente leitura. Em produção, indique uma pasta privada do servidor no `.env`:

```env
TEMPLATES_HOST_DIR=/opt/sankhya-proposal/templates
```

Copie para essa pasta privada `Cabecalho.docx`, `Itens.docx`, `Condicoes.docx` e `Dados.xlsx`. Alterações feitas nos arquivos do host ficam disponíveis ao container sem reconstruir a imagem. Mantenha backup separado e controle de acesso nessa pasta.

Documentos intermediários, PDFs e o perfil isolado do LibreOffice ficam no `tmpfs` `/tmp` e desaparecem quando o container é encerrado. A aplicação roda como usuário não-root, com filesystem somente leitura, healthcheck e um worker de conversão.

Para encerrar:

```powershell
docker compose down
```

### Fontes

A imagem contém DejaVu e Liberation. Aptos e Calibri podem ser substituídas pelo LibreOffice, causando pequenas diferenças de espaçamento ou paginação. Quando a fidelidade exata for necessária, fontes Microsoft devidamente licenciadas devem ser adicionadas a uma imagem privada e registradas com `fc-cache`; fontes proprietárias não devem ser versionadas sem a licença correspondente.
