from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProposalHeader(BaseModel):
    model_config = ConfigDict(extra="allow")

    IdMemoria: Any = None
    DataProposta: Any = None
    CodParceiro: Any = None
    Cliente: Any = None
    CodTipoOperacao: Any = None
    TipoOperacao: Any = None
    CodTipoVenda: Any = None
    CondicaoPagamento: Any = None
    CodMoeda: Any = None
    Moeda: Any = None
    DataTaxa: Any = None
    CodEmpresa: Any = None
    Empresa: Any = None
    ValorTaxa: Any = None
    CodControle: Any = None
    DescricaoControle: Any = None
    NuNota: Any = None
    CodClassificacao: Any = None
    Classificacao: Any = None
    Status: Any = None
    CifFob: Any = None
    ValorFrete: Any = None
    DataAprovacao: Any = None
    UsuarioAprovador: Any = None
    CodNatureza: Any = None
    Natureza: Any = None
    CodCentroResultado: Any = None
    CentroResultado: Any = None
    IdAnterior: Any = None
    Revisao: Any = None
    ValorNota: Any = None
    Observacao: Any = None


class ProposalItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    Sequencia: Any = None
    CodProd: Any = None
    DescricaoProduto: Any = None
    NCM: Any = None
    Quantidade: Any = None
    ValorUnitLiquido: Any = None
    ValorTotalLiquido: Any = None
    ValorUnitPisCofins: Any = None
    AliqICMS: Any = None
    ValorTotalICMS: Any = None
    ValorUnitICMS: Any = None
    AliqIPI: Any = None
    ValorUnitIPI: Any = None
    ValorTotalIPI: Any = None
    CodigoTemplate: Any = None
    DescricaoCompleta: Any = None
    PrevisaoEntrega: Any = None
    Homepage: str = ""
    PdfBase64: str = ""


class Proposal(BaseModel):
    Cabecalho: ProposalHeader | None
    Vendedor: str
    Itens: list[ProposalItem]


class GetProposalResponse(BaseModel):
    sucesso: bool = True
    mensagem: str = "Proposta encontrada"
    proposta: Proposal


class ErrorResponse(BaseModel):
    sucesso: bool = False
    mensagem: str
    correlation_id: str | None = Field(default=None)


class CreateProposalPdfRequest(BaseModel):
    proposta: Proposal
    responsavel: str = ""
    email_cliente: str = ""
