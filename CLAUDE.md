# Contexto do projeto — Radar Senado × Mercado

## Objetivo
Ligar votações nominais do Senado a impacto em setores e tickers da B3, para responder "o que essa votação faz com meu portfólio e quem decide". Não é um app genérico de "quem votou em quê": esse espaço já tem ferramentas gratuitas, como o Radar do Congresso, do Congresso em Foco. O diferencial é a camada de mercado.

Usos previstos: insumo interno de risco político para a Ciano Investimentos, conteúdo recorrente para o Instagram @ciano.invest e, se validar, produto B2B para gestoras e assessorias.

## Stack
- Supabase (Postgres): `supabase/schema.sql` e `supabase/seed.sql`, ambos idempotentes.
- Ingestão em Python: `ingest/ingest.py` (psycopg + requests).
- GitHub Actions: `.github/workflows/ingestao.yml`, roda seg–sex às 23h17 BRT e precisa do secret `DATABASE_URL`.
- Front ainda não existe. A ideia é usar Next.js + Supabase, a mesma stack do projeto fit-padel.

## Decisões de modelagem (não mudar sem motivo)
- A ingestão só detecta o setor afetado, por palavra-chave na ementa: grava `origem='auto'` com `impacto=null`. A direção do impacto (-2..+2, efeito se a matéria for aprovada) é decisão manual do analista, feita pela view `v_fila_classificacao`.
- Pontuação de cada voto: SIM vale +impacto, NAO vale -impacto. Ausência, licença e abstenção não pontuam.
- Só pontuam votações com `tipo='merito'`, nominais e abertas. Em destaque e requerimento, "Sim" não significa aprovar a matéria.
- O `tipo` é heurístico (regex em `tipo_votacao()`). `tipo_manual=true` trava a correção feita à mão contra a próxima ingestão.
- `votos.partido_na_data` guarda o partido no dia do voto, porque senadores trocam de partido.
- `votos.sigla_original` é preservada e `votos.categoria` guarda a forma normalizada.

## API do Senado: armadilhas conhecidas
- O endpoint legado `/plenario/lista/votacao` foi desativado em 01/02/2026. O atual é `GET https://legis.senado.leg.br/dadosabertos/votacao?dataInicio=AAAA-MM-DD&dataFim=AAAA-MM-DD`, que devolve um array na raiz com `votos[]` embutido.
- `totalVotosSim/Nao/Abstencao` vêm null, por isso o placar é recontado a partir de `votos[]`.
- `siglaVotoParlamentar` não é um enum limpo: Sim, Não, Abstenção, AP, P-NRV, MIS, LS, LAP, LP, "Presidente (art. 51 RISF)" e "Votou" (em votação secreta).
- Rate limit com 429/503: o script faz 1 req/s com backoff exponencial.
- Votação secreta (Mesa, sabatinas, autoridades) não tem voto individual. Votação simbólica não aparece na API.

## Estado atual (27/10/2026)
- Schema, seed e ingestão foram testados ponta a ponta num Postgres local com o fixture SINTÉTICO de `ingest/fixtures/`. Os nomes de campo vieram de projetos abertos que já usam a API (votosdosenado, politicapp).
- **NUNCA RODOU CONTRA A API REAL**: o ambiente onde o código foi escrito não tinha acesso de rede ao senado.leg.br.

## Próximos passos
1. Rodar `python ingest/ingest.py votacoes --inicio 2026-09-01 --fim 2026-09-30` contra a API real e comparar campos e formatos com o que o código espera (`codigoSessaoVotacao`, `dataSessao`, `votacaoSecreta`, `codigoMateria`, `sigla`, `numero`, `ano`, `ementa`, `votos[].codigoParlamentar`, `siglaPartidoParlamentar`, `siglaUFParlamentar`, `siglaVotoParlamentar`).
2. Conferir as descrições reais de votação e ajustar `REGRAS_TIPO` em `ingest.py`.
3. Salvar uma amostra real em `ingest/fixtures/` e escrever testes com pytest em cima dela.
4. Fazer a carga histórica desde 2023-02-01 e revisar falsos positivos da classificação por palavra-chave.
5. Montar o front: página por senador, página por setor/ticker e um "placar provável" de matérias em tramitação.
