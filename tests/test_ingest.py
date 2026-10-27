"""Testes da ingestão em cima da amostra REAL da API do Senado (set/2026).

A amostra `ingest/fixtures/votacoes_set2026_real.json` foi puxada ao vivo do
endpoint `/dadosabertos/votacao` e tem 2 votações:
  - PDL 995/2026: escolha de Ministro do TCU (autoridade), votação secreta,
    totalVotos* preenchidos pela API;
  - PLP 74/2026: projeto de lei complementar (mérito), votação aberta,
    totalVotos* nulos (placar recontado a partir de votos[]).
"""

import json
from pathlib import Path

import pytest

import ingest

FIXTURE = Path(__file__).resolve().parent.parent / "ingest" / "fixtures" / "votacoes_set2026_real.json"


@pytest.fixture(scope="module")
def votacoes():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def por_id(votacoes):
    return {v["identificacao"]: v for v in votacoes}


# --------------------------------------------------------------------------
# normalizar
# --------------------------------------------------------------------------


def test_normalizar_tira_acento_caixa_e_espacos():
    assert ingest.normalizar("Votação   NOMINAL  do Projeto") == "votacao nominal do projeto"
    assert ingest.normalizar(None) == ""


# --------------------------------------------------------------------------
# categoria_voto
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sigla,esperado",
    [
        ("Sim", "SIM"),
        ("Não", "NAO"),
        ("Abstenção", "ABST"),
        ("AP", "LICENCA"),
        ("P-NRV", "AUSENTE"),
        ("Votou", "SECRETO"),
        ("Presidente (art. 51 RISF)", "PRESIDENTE"),
        (None, "AUSENTE"),
        ("sigla desconhecida", "AUSENTE"),
    ],
)
def test_categoria_voto(sigla, esperado):
    assert ingest.categoria_voto(sigla) == esperado


def test_categoria_voto_cobre_todas_as_siglas_da_amostra(votacoes):
    siglas = {voto["siglaVotoParlamentar"] for v in votacoes for voto in v["votos"]}
    # valores que de fato aparecem na amostra real
    assert siglas == {"Sim", "AP", "P-NRV", "Votou", "Presidente (art. 51 RISF)"}
    # nenhuma delas é um valor realmente desconhecido tratado como ausência por engano
    categorias_validas = {"SIM", "NAO", "ABST", "OBSTRUCAO", "LICENCA", "SECRETO", "PRESIDENTE", "AUSENTE"}
    assert {ingest.categoria_voto(s) for s in siglas} <= categorias_validas


# --------------------------------------------------------------------------
# tipo_votacao — a correção central: o assunto vem da ementa, não da descrição
# --------------------------------------------------------------------------


def test_tipo_pdl_autoridade_so_aparece_com_a_ementa(por_id):
    v = por_id["PDL 995/2026"]
    # a descrição sozinha é boilerplate "Projeto de Decreto Legislativo" -> daria mérito
    assert ingest.tipo_votacao(v["descricaoVotacao"], None, v["sigla"]) == "merito"
    # com a ementa ("...Ministro do Tribunal de Contas...") vira autoridade
    assert ingest.tipo_votacao(v["descricaoVotacao"], v["ementa"], v["sigla"]) == "autoridade"


def test_tipo_plp_segue_merito(por_id):
    v = por_id["PLP 74/2026"]
    assert ingest.tipo_votacao(v["descricaoVotacao"], v["ementa"], v["sigla"]) == "merito"


@pytest.mark.parametrize(
    "descricao,ementa,sigla,esperado",
    [
        ("Votação do Requerimento de urgência", None, "PL", "requerimento"),
        ("Votação nominal do destaque", None, "PL", "destaque"),
        ("Votação nominal", "Indicação do nome do diretor da agência", None, "autoridade"),
        ("texto genérico sem pista", None, "PEC", "merito"),  # fallback pela sigla
        ("texto genérico sem pista", None, None, "outro"),
    ],
)
def test_tipo_votacao_casos(descricao, ementa, sigla, esperado):
    assert ingest.tipo_votacao(descricao, ementa, sigla) == esperado


# --------------------------------------------------------------------------
# para_timestamp / lista
# --------------------------------------------------------------------------


def test_para_timestamp_data_sem_hora(por_id):
    dt = ingest.para_timestamp(por_id["PDL 995/2026"]["dataSessao"])
    assert (dt.year, dt.month, dt.day) == (2026, 9, 1)
    assert dt.tzinfo is not None  # recebe America/Sao_Paulo quando a API manda só a data


def test_para_timestamp_none():
    assert ingest.para_timestamp(None) is None


def test_lista_normaliza_none_e_objeto_unico():
    assert ingest.lista(None) == []
    assert ingest.lista({"a": 1}) == [{"a": 1}]
    assert ingest.lista([1, 2]) == [1, 2]


# --------------------------------------------------------------------------
# ingerir_votacoes — integração com um cursor falso (sem banco)
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        self.rowcount = 0


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def _votacoes_inseridas(cur):
    """codigo -> params do INSERT em votacoes.

    Ordem: codigo, data, descricao, resultado, secreta, materia, tipo,
           total_sim, total_nao, total_abst, raw.
    """
    out = {}
    for sql, params in cur.calls:
        if sql.startswith("insert into votacoes"):
            out[params[0]] = params
    return out


def test_ingerir_votacoes_na_amostra_real(votacoes):
    con = _FakeConn()
    n_votacoes, n_votos = ingest.ingerir_votacoes(con, votacoes)

    assert n_votacoes == 2
    assert n_votos == 162  # 81 + 81

    inseridas = _votacoes_inseridas(con.cur)
    assert set(inseridas) == {"7104", "7105"}

    # PDL 995 (secreta): tipo corrigido para autoridade; placar vem do agregado da API (63)
    pdl = inseridas["7104"]
    assert pdl[4] is True          # secreta
    assert pdl[5] == "175624"      # materia_codigo
    assert pdl[6] == "autoridade"  # tipo
    assert pdl[7] == 63            # total_sim (API trouxe preenchido)

    # PLP 74 (aberta): tipo mérito; total_sim recontado de votos[] porque a API veio null
    plp = inseridas["7105"]
    assert plp[4] is False         # secreta
    assert plp[6] == "merito"      # tipo
    assert plp[7] == 66            # recontagem: 66 votos "Sim"
    assert plp[8] == 0             # nenhum "Não"
