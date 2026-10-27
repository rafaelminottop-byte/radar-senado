# Radar Senado × Mercado

Liga as votações nominais do Senado ao impacto em setores e tickers da B3.
A pergunta que o projeto responde não é "quem votou em quê", e sim **"o que isso faz com meu portfólio, e quem decide"**.

## Estrutura

```
supabase/schema.sql      tabelas, views analíticas e RLS (leitura pública, escrita só service role)
supabase/seed.sql        14 setores, palavras-chave por setor, 35 tickers de referência
ingest/ingest.py         coleta na API de Dados Abertos do Senado e grava no Postgres
ingest/fixtures/         JSON SINTÉTICO no formato da API, para teste offline
.github/workflows/       cron diário (seg–sex, 23h17 BRT) + carga histórica manual
```

## Subir em 4 passos

1. **Supabase:** crie um projeto, abra o SQL Editor e rode `schema.sql` e depois `seed.sql`. Os dois são idempotentes.
2. **Conexão:** copie a connection string (Settings → Database, modo *Session pooler*) e exporte como `DATABASE_URL`.
3. **Carga histórica** (legislatura atual):
   ```bash
   pip install -r ingest/requirements.txt
   python ingest/ingest.py tudo --inicio 2023-02-01
   ```
   São cerca de 45 janelas mensais a 1 req/s, o que deve levar poucos minutos.
4. **Automação:** suba o repositório no GitHub, cadastre o secret `DATABASE_URL` e o workflow passa a rodar sozinho.

## Como o índice funciona

1. A ingestão liga cada matéria aos setores cuja palavra-chave aparece na ementa (`origem = 'auto'`, `impacto = null`).
2. O analista abre `v_fila_classificacao` e preenche `materia_setor.impacto` de **-2 a +2** (efeito no setor *se aprovada*), marcando `origem = 'manual'`.
3. Cada voto pontua: `SIM` vale `+impacto` e `NAO` vale `-impacto`. Ausência, licença e abstenção não pontuam.
4. `v_alinhamento_setor` dá o índice de -100 (sempre votou contra o setor) a +100 (sempre a favor), com o número de votações por trás.

Só entram votações de **mérito**, nominais e abertas. Em destaque e requerimento, votar "Sim" não equivale a aprovar a matéria.

## Views

| View | Para quê |
|---|---|
| `v_placar` | placar recontado de cada votação (a API devolve os totais `null`) |
| `v_alinhamento_setor` | senador × setor, índice -100..+100 |
| `v_alinhamento_geral` | índice agregado em todas as pautas com impacto avaliado |
| `v_votacoes_por_ticker` | votações que afetam cada ticker |
| `v_fila_classificacao` | matérias com setor detectado e impacto ainda não avaliado |

## Limitações conhecidas

- **Votações secretas não têm voto individual.** A eleição da Mesa, sabatinas e indicações de autoridade chegam só como `Votou`.
- **Votação simbólica não aparece.** Só há voto por senador em votação nominal, e a maior parte das matérias passa de forma simbólica.
- **O tipo da votação é heurístico** (regex na descrição). Revise os casos importantes e marque `tipo_manual = true`, para que a ingestão não sobrescreva a correção.
- **Palavra-chave gera falso positivo.** Por isso a ligação automática nunca vem com impacto preenchido: a direção é sempre decisão do analista.
- **Índice com poucas votações é ruído.** Na interface, só exiba o índice a partir de umas 5 votações pontuadas no setor.

## Notas da API (custaram tempo a outros projetos)

- O endpoint legado `/plenario/lista/votacao` foi **desativado em 01/02/2026**. O atual é `/dadosabertos/votacao?dataInicio=AAAA-MM-DD&dataFim=AAAA-MM-DD`, que devolve um array na raiz com `votos[]` embutido.
- `siglaVotoParlamentar` mistura `Sim`/`Não`/`Abstenção` com `AP`, `P-NRV`, `MIS`, `LS`, `LAP`, `LP` e `Presidente (art. 51 RISF)`. A sigla original fica em `votos.sigla_original` e a categoria normalizada em `votos.categoria`.
- A API responde 429/503 sob carga. O script faz 1 req/s com backoff exponencial.
