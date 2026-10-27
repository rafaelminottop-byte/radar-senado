"""Ingestão de votações do Senado para o Radar Senado × Mercado.

Uso:
    python ingest.py senadores
    python ingest.py votacoes --inicio 2023-02-01 [--fim 2026-10-27]
    python ingest.py classificar
    python ingest.py tudo --inicio 2023-02-01        # senadores + votações + classificação

    # teste offline, sem chamar a API:
    python ingest.py votacoes --fixture caminho/votacoes.json
    python ingest.py senadores --fixture caminho/senadores.json

Requer a variável DATABASE_URL (string de conexão Postgres do Supabase, papel com escrita).

Fonte: API de Dados Abertos do Senado.
  - /dadosabertos/votacao?dataInicio=AAAA-MM-DD&dataFim=AAAA-MM-DD
      resposta = array na raiz; cada votação traz votos[] embutidos.
      totalVotosSim/Nao/Abstencao às vezes vêm null (visto em votação aberta); quando null,
      o placar é recontado a partir de votos[]. descricaoVotacao é um texto padrão
      ("Votação nominal do Projeto ... nº X"); o assunto real está em ementa.
  - /dadosabertos/senador/lista/atual
O endpoint legado /plenario/lista/votacao foi desativado em 01/02/2026; não use.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import psycopg
import requests
from psycopg.types.json import Jsonb

BASE = "https://legis.senado.leg.br/dadosabertos"
TZ = ZoneInfo("America/Sao_Paulo")
PAUSA_ENTRE_REQUISICOES = 1.0  # a API devolve 429/503 sob carga; 1 req/s é seguro

# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


def normalizar(texto: str | None) -> str:
    """Minúsculas, sem acento, espaços colapsados."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


# siglaVotoParlamentar não é um enum limpo. Sigla original é preservada; esta é a categoria analítica.
MAPA_VOTO = {
    "sim": "SIM",
    "nao": "NAO",
    "abstencao": "ABST",
    "abst": "ABST",
    "obstrucao": "OBSTRUCAO",
    "p-nrv": "AUSENTE",       # presente, não registrou voto
    "nao registrou voto": "AUSENTE",
    "ausente": "AUSENTE",
    "ap": "LICENCA",          # atividade parlamentar
    "mis": "LICENCA",         # missão
    "ls": "LICENCA",          # licença saúde
    "lap": "LICENCA",         # licença atividade parlamentar
    "lp": "LICENCA",          # licença particular
    "votou": "SECRETO",       # votação secreta: só se sabe que votou
}


def categoria_voto(sigla: str | None) -> str:
    n = normalizar(sigla)
    if n.startswith("presidente"):
        return "PRESIDENTE"
    return MAPA_VOTO.get(n, "AUSENTE")


# Classificação heurística do tipo de votação a partir da descrição.
# Só 'merito' entra no índice de alinhamento: em destaque/requerimento "Sim" não significa aprovar a matéria.
# A heurística é revisável: marque votacoes.tipo_manual = true para travar uma correção feita à mão.
REGRAS_TIPO = [
    ("destaque", re.compile(r"\bdestaque|\bdvs\b|\bemenda\b.*\bdestacad")),
    ("requerimento", re.compile(r"\brequerimento|\burgencia\b|\badiamento\b|\bcalendario especial")),
    ("autoridade", re.compile(r"\bindicacao\b|\bescolha de\b|\bembaixador|\bmensagem\b|\bdiretor|\bministro do|\bconselheir|\bprocurador-geral")),
    ("merito", re.compile(r"\bprojeto\b|\bproposta de emenda|\bpec\b|\bmedida provisoria|\bsubstitutivo|\bturno\b|\bredacao final|\bplp\b|\bpl\b|\bpdl\b|\bveto")),
]


def tipo_votacao(descricao: str | None, ementa: str | None, sigla_materia: str | None) -> str:
    # descricaoVotacao na API atual é um texto padrão ("Votação nominal do Projeto ... nº X, de AAAA");
    # o assunto real (autoridade, destaque, requerimento) só aparece na ementa. Classificamos sobre os dois.
    n = f"{normalizar(descricao)} {normalizar(ementa)}".strip()
    for tipo, padrao in REGRAS_TIPO:
        if padrao.search(n):
            return tipo
    # sem pista na descrição, mas ligada a projeto de lei/PEC/MP: provável mérito
    if (sigla_materia or "").upper() in {"PL", "PLS", "PLC", "PLP", "PEC", "MPV", "PLV", "PDL", "PRS"}:
        return "merito"
    return "outro"


def para_timestamp(valor: str | None) -> datetime | None:
    if not valor:
        return None
    dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def lista(x: Any) -> list:
    """A API às vezes devolve objeto único onde se espera lista."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_sessao = requests.Session()
_sessao.headers.update({"Accept": "application/json", "User-Agent": "radar-senado/0.1"})


def buscar(caminho: str, params: dict | None = None, tentativas: int = 5) -> Any:
    url = f"{BASE}{caminho}"
    for i in range(tentativas):
        try:
            r = _sessao.get(url, params=params, timeout=90)
            if r.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            if r.status_code == 404:
                return []
            r.raise_for_status()
            time.sleep(PAUSA_ENTRE_REQUISICOES)
            return r.json() if r.content else []
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            espera = 2 ** i
            print(f"  ! {e} em {url} {params or ''}; nova tentativa em {espera}s", file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"Falhou após {tentativas} tentativas: {url} {params}")


def janelas_mensais(inicio: date, fim: date) -> Iterable[tuple[date, date]]:
    atual = inicio
    while atual <= fim:
        prox_mes = (atual.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield atual, min(prox_mes - timedelta(days=1), fim)
        atual = prox_mes


# ---------------------------------------------------------------------------
# Senadores
# ---------------------------------------------------------------------------


def ingerir_senadores(con: psycopg.Connection, payload: dict | None = None) -> int:
    dados = payload if payload is not None else buscar("/senador/lista/atual")
    registros = lista(dados["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"])
    codigos = []
    with con.cursor() as cur:
        for reg in registros:
            ident = reg.get("IdentificacaoParlamentar", {})
            bloco = ident.get("Bloco") or {}
            codigo = str(ident["CodigoParlamentar"])
            codigos.append(codigo)
            cur.execute(
                """
                insert into senadores (codigo, nome, nome_civil, partido, uf, bloco, foto_url, em_exercicio, atualizado_em)
                values (%s, %s, %s, %s, %s, %s, %s, true, now())
                on conflict (codigo) do update set
                  nome = excluded.nome, nome_civil = excluded.nome_civil, partido = excluded.partido,
                  uf = excluded.uf, bloco = excluded.bloco, foto_url = excluded.foto_url,
                  em_exercicio = true, atualizado_em = now()
                """,
                (
                    codigo,
                    ident.get("NomeParlamentar") or "Sem nome",
                    ident.get("NomeCompletoParlamentar"),
                    ident.get("SiglaPartidoParlamentar"),
                    ident.get("UfParlamentar") or (reg.get("Mandato") or {}).get("UfParlamentar"),
                    bloco.get("NomeApelido") or bloco.get("NomeBloco"),
                    (ident.get("UrlFotoParlamentar") or "").replace("http://", "https://", 1) or None,
                ),
            )
        # quem saiu da lista atual deixa de estar em exercício (o histórico de votos fica)
        cur.execute(
            "update senadores set em_exercicio = false, atualizado_em = now() "
            "where em_exercicio and not (codigo = any(%s))",
            (codigos,),
        )
    con.commit()
    return len(codigos)


# ---------------------------------------------------------------------------
# Votações
# ---------------------------------------------------------------------------


def _upsert_materia(cur: psycopg.Cursor, reg: dict) -> str | None:
    codigo = reg.get("codigoMateria")
    if codigo is None:
        return None
    codigo = str(codigo)
    cur.execute(
        """
        insert into materias (codigo, sigla, numero, ano, ementa)
        values (%s, %s, %s, %s, %s)
        on conflict (codigo) do update set
          sigla = coalesce(excluded.sigla, materias.sigla),
          numero = coalesce(excluded.numero, materias.numero),
          ano = coalesce(excluded.ano, materias.ano),
          ementa = coalesce(excluded.ementa, materias.ementa)
        """,
        (
            codigo,
            reg.get("sigla"),
            str(reg["numero"]) if reg.get("numero") is not None else None,
            int(reg["ano"]) if reg.get("ano") else None,
            reg.get("ementa") or None,
        ),
    )
    return codigo


def ingerir_votacoes(con: psycopg.Connection, registros: list[dict]) -> tuple[int, int]:
    n_votacoes = n_votos = 0
    with con.cursor() as cur:
        for reg in registros:
            codigo = str(reg.get("codigoSessaoVotacao") or reg.get("sequencialVotacao") or "")
            data = para_timestamp(reg.get("dataSessao"))
            if not codigo or data is None:
                print(f"  ! votação sem código/data ignorada: {json.dumps(reg)[:200]}", file=sys.stderr)
                continue

            materia = _upsert_materia(cur, reg)
            votos = lista(reg.get("votos"))
            cats = [categoria_voto(v.get("siglaVotoParlamentar")) for v in votos]
            secreta = str(reg.get("votacaoSecreta") or "").upper() in {"S", "SIM", "TRUE", "1"}

            cur.execute(
                """
                insert into votacoes (codigo, data_sessao, descricao, resultado, secreta, materia_codigo,
                                      tipo, total_sim, total_nao, total_abst, raw)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (codigo) do update set
                  data_sessao = excluded.data_sessao, descricao = excluded.descricao,
                  resultado = excluded.resultado, secreta = excluded.secreta,
                  materia_codigo = excluded.materia_codigo,
                  tipo = case when votacoes.tipo_manual then votacoes.tipo else excluded.tipo end,
                  total_sim = excluded.total_sim, total_nao = excluded.total_nao,
                  total_abst = excluded.total_abst, raw = excluded.raw
                """,
                (
                    codigo,
                    data,
                    reg.get("descricaoVotacao"),
                    str(reg.get("resultadoVotacao") or "") or None,
                    secreta,
                    materia,
                    tipo_votacao(reg.get("descricaoVotacao"), reg.get("ementa"), reg.get("sigla")),
                    reg.get("totalVotosSim") if reg.get("totalVotosSim") is not None else cats.count("SIM"),
                    reg.get("totalVotosNao") if reg.get("totalVotosNao") is not None else cats.count("NAO"),
                    reg.get("totalVotosAbstencao") if reg.get("totalVotosAbstencao") is not None else cats.count("ABST"),
                    Jsonb(reg),
                ),
            )

            for v, cat in zip(votos, cats):
                sen = str(v.get("codigoParlamentar") or "")
                if not sen:
                    continue
                # senador fora da lista atual (ex-titular, suplente que saiu): cria registro mínimo
                cur.execute(
                    """
                    insert into senadores (codigo, nome, partido, uf, em_exercicio)
                    values (%s, %s, %s, %s, false)
                    on conflict (codigo) do nothing
                    """,
                    (sen, v.get("nomeParlamentar") or "Sem nome",
                     v.get("siglaPartidoParlamentar"), v.get("siglaUFParlamentar")),
                )
                cur.execute(
                    """
                    insert into votos (votacao_codigo, senador_codigo, partido_na_data, uf, sigla_original, categoria)
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (votacao_codigo, senador_codigo) do update set
                      partido_na_data = excluded.partido_na_data, uf = excluded.uf,
                      sigla_original = excluded.sigla_original, categoria = excluded.categoria
                    """,
                    (codigo, sen, v.get("siglaPartidoParlamentar"), v.get("siglaUFParlamentar"),
                     v.get("siglaVotoParlamentar") or "", cat),
                )
                n_votos += 1
            n_votacoes += 1
            if n_votacoes % 100 == 0:
                con.commit()
    con.commit()
    return n_votacoes, n_votos


def baixar_votacoes(inicio: date, fim: date) -> Iterable[list[dict]]:
    for a, b in janelas_mensais(inicio, fim):
        print(f"  votações {a} → {b}")
        dados = buscar("/votacao", {"dataInicio": a.isoformat(), "dataFim": b.isoformat()})
        yield lista(dados)


# ---------------------------------------------------------------------------
# Classificação matéria → setor (por palavras-chave na ementa)
# ---------------------------------------------------------------------------


def _padrao_termo(termo: str) -> re.Pattern:
    termo = normalizar(termo)
    # termos curtos (siglas como jcp, fii, ans, ipi) exigem palavra inteira; os demais casam como prefixo
    fim = r"\b" if len(termo) <= 5 else ""
    return re.compile(r"\b" + re.escape(termo) + fim)


def classificar_materias(con: psycopg.Connection, reclassificar: bool = False) -> int:
    """Liga matérias a setores. Só insere origem='auto' com impacto null; nunca toca em linhas manuais."""
    with con.cursor() as cur:
        cur.execute("select setor_id, termo from setor_palavras")
        regras: dict[str, list[re.Pattern]] = {}
        for setor, termo in cur.fetchall():
            regras.setdefault(setor, []).append(_padrao_termo(termo))

        if reclassificar:
            cur.execute("delete from materia_setor where origem = 'auto' and impacto is null")
        cur.execute(
            """
            select m.codigo, m.ementa from materias m
            where m.ementa is not null
              and not exists (select 1 from materia_setor ms where ms.materia_codigo = m.codigo)
            """
        )
        n = 0
        for codigo, ementa in cur.fetchall():
            texto = normalizar(ementa)
            for setor, padroes in regras.items():
                if any(p.search(texto) for p in padroes):
                    cur.execute(
                        "insert into materia_setor (materia_codigo, setor_id, origem) values (%s, %s, 'auto') "
                        "on conflict do nothing",
                        (codigo, setor),
                    )
                    n += cur.rowcount
    con.commit()
    return n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando", choices=["senadores", "votacoes", "classificar", "tudo"])
    p.add_argument("--inicio", type=date.fromisoformat, help="AAAA-MM-DD")
    p.add_argument("--fim", type=date.fromisoformat, default=date.today(), help="AAAA-MM-DD (padrão: hoje)")
    p.add_argument("--fixture", help="JSON local no formato da API, no lugar da chamada HTTP")
    p.add_argument("--reclassificar", action="store_true", help="refaz ligações automáticas sem impacto avaliado")
    a = p.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Defina DATABASE_URL com a string de conexão do Supabase.")

    with psycopg.connect(dsn) as con:
        if a.comando in ("senadores", "tudo"):
            payload = json.load(open(a.fixture)) if a.fixture and a.comando == "senadores" else None
            print(f"senadores em exercício: {ingerir_senadores(con, payload)}")

        if a.comando in ("votacoes", "tudo"):
            total_v = total_votos = 0
            if a.fixture and a.comando == "votacoes":
                lotes: Iterable[list[dict]] = [lista(json.load(open(a.fixture)))]
            else:
                if not a.inicio:
                    sys.exit("Informe --inicio para baixar votações.")
                lotes = baixar_votacoes(a.inicio, a.fim)
            for lote in lotes:
                v, vt = ingerir_votacoes(con, lote)
                total_v += v
                total_votos += vt
            print(f"votações: {total_v} | votos individuais: {total_votos}")

        if a.comando in ("classificar", "votacoes", "tudo"):
            print(f"ligações matéria→setor novas: {classificar_materias(con, a.reclassificar)}")


if __name__ == "__main__":
    main()
