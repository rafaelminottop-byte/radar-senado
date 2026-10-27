-- Radar Senado × Mercado — schema (Supabase / Postgres 15+)
-- Pergunta que o modelo responde: "o que as votações do Senado fazem com meu portfólio?"
-- Fonte: API de Dados Abertos do Senado (/dadosabertos/votacao e /dadosabertos/senador/lista/atual)

-- ============================================================
-- 1. Dados brutos do Senado
-- ============================================================

create table if not exists senadores (
  codigo          text primary key,          -- codigoParlamentar da API
  nome            text not null,
  nome_civil      text,
  partido         text,                      -- partido atual
  uf              char(2),
  bloco           text,
  foto_url        text,
  em_exercicio    boolean not null default false,
  atualizado_em   timestamptz not null default now()
);

create table if not exists materias (
  codigo          text primary key,          -- codigoMateria
  sigla           text,                      -- PL, PEC, PLP, MPV...
  numero          text,
  ano             int,
  ementa          text,
  url             text generated always as
                  ('https://www25.senado.leg.br/web/atividade/materias/-/materia/' || codigo) stored
);

-- Tipo da votação: só "merito" entra no índice. Destaque/requerimento têm sentido de voto ambíguo.
do $$ begin
  create type tipo_votacao as enum ('merito', 'destaque', 'requerimento', 'autoridade', 'outro');
exception when duplicate_object then null; end $$;

do $$ begin
  create type categoria_voto as enum ('SIM', 'NAO', 'ABST', 'OBSTRUCAO', 'AUSENTE', 'LICENCA', 'PRESIDENTE', 'SECRETO');
exception when duplicate_object then null; end $$;

create table if not exists votacoes (
  codigo          text primary key,          -- codigoSessaoVotacao (fallback: sequencialVotacao)
  data_sessao     timestamptz not null,
  descricao       text,
  resultado       text,                      -- resultadoVotacao (A = aprovado, R = rejeitado...)
  secreta         boolean not null default false,
  materia_codigo  text references materias(codigo),
  tipo            tipo_votacao not null default 'outro',
  tipo_manual     boolean not null default false,  -- true = classificação revisada à mão, ingestão não sobrescreve
  total_sim       int,                       -- API devolve null: recalculado de votos[]
  total_nao       int,
  total_abst      int,
  raw             jsonb                      -- registro original, para reprocessar sem rebaixar
);
create index if not exists votacoes_data_idx on votacoes (data_sessao desc);
create index if not exists votacoes_materia_idx on votacoes (materia_codigo);

create table if not exists votos (
  votacao_codigo  text not null references votacoes(codigo) on delete cascade,
  senador_codigo  text not null references senadores(codigo),
  partido_na_data text,                      -- partido no dia do voto (senador troca de partido)
  uf              char(2),
  sigla_original  text not null,             -- siglaVotoParlamentar crua (AP, P-NRV, MIS, LS...)
  categoria       categoria_voto not null,
  primary key (votacao_codigo, senador_codigo)
);
create index if not exists votos_senador_idx on votos (senador_codigo);

-- ============================================================
-- 2. Camada de mercado (o diferencial)
-- ============================================================

create table if not exists setores (
  id              text primary key,          -- slug: bancos, eletricas, saneamento...
  nome            text not null
);

create table if not exists ativos (
  ticker          text primary key,          -- ITUB4, ELET3...
  empresa         text not null,
  setor_id        text not null references setores(id)
);

-- Palavras-chave que sugerem que uma matéria afeta um setor (classificação automática inicial)
create table if not exists setor_palavras (
  setor_id        text not null references setores(id) on delete cascade,
  termo           text not null,             -- comparado sem acento, case-insensitive, contra a ementa
  primary key (setor_id, termo)
);

-- Impacto de uma matéria num setor. Escala: -2 (muito negativo) .. +2 (muito positivo) se APROVADA.
-- impacto null = setor afetado, direção ainda não avaliada (classificação automática só acha o setor).
create table if not exists materia_setor (
  materia_codigo  text not null references materias(codigo) on delete cascade,
  setor_id        text not null references setores(id),
  impacto         smallint check (impacto between -2 and 2),
  origem          text not null default 'auto' check (origem in ('auto', 'manual')),
  nota            text,
  primary key (materia_codigo, setor_id)
);

-- ============================================================
-- 3. Views analíticas
-- ============================================================

-- Placar recalculado por votação
create or replace view v_placar as
select v.codigo, v.data_sessao, v.descricao, v.tipo, v.resultado, v.secreta,
       m.sigla || ' ' || m.numero || '/' || m.ano as materia, m.ementa,
       count(*) filter (where vt.categoria = 'SIM')  as sim,
       count(*) filter (where vt.categoria = 'NAO')  as nao,
       count(*) filter (where vt.categoria = 'ABST') as abst,
       count(*) filter (where vt.categoria in ('AUSENTE','LICENCA')) as fora
from votacoes v
left join materias m on m.codigo = v.materia_codigo
left join votos vt on vt.votacao_codigo = v.codigo
group by v.codigo, m.codigo;

-- Pontuação de cada voto por setor:
--   SIM numa matéria de impacto +2 para bancos  => +2 para bancos
--   NAO numa matéria de impacto +2 para bancos  => -2 para bancos
-- Só votações de mérito, nominais e com impacto avaliado.
create or replace view v_voto_setor as
select vt.senador_codigo, ms.setor_id, v.codigo as votacao_codigo, v.data_sessao,
       case vt.categoria when 'SIM' then ms.impacto
                         when 'NAO' then -ms.impacto end as pontos
from votos vt
join votacoes v       on v.codigo = vt.votacao_codigo
join materia_setor ms on ms.materia_codigo = v.materia_codigo
where v.tipo = 'merito' and not v.secreta
  and ms.impacto is not null and ms.impacto <> 0
  and vt.categoria in ('SIM', 'NAO');

-- Índice de alinhamento senador × setor: -100 (sempre contra o setor) .. +100 (sempre a favor)
create or replace view v_alinhamento_setor as
select s.codigo, s.nome, s.partido, s.uf, vs.setor_id,
       count(*) as votacoes,
       round(100.0 * sum(vs.pontos) / sum(abs(vs.pontos)), 1) as indice
from v_voto_setor vs
join senadores s on s.codigo = vs.senador_codigo
group by s.codigo, vs.setor_id;

-- Índice agregado (todas as pautas com impacto avaliado): proxy de "alinhamento pró-mercado"
create or replace view v_alinhamento_geral as
select s.codigo, s.nome, s.partido, s.uf, s.em_exercicio,
       count(*) as votos_pontuados,
       round(100.0 * sum(vs.pontos) / nullif(sum(abs(vs.pontos)), 0), 1) as indice
from v_voto_setor vs
join senadores s on s.codigo = vs.senador_codigo
group by s.codigo;

-- Votações que afetam cada ticker
create or replace view v_votacoes_por_ticker as
select a.ticker, a.empresa, a.setor_id, ms.impacto, p.*
from ativos a
join materia_setor ms on ms.setor_id = a.setor_id
join votacoes v on v.materia_codigo = ms.materia_codigo
join v_placar p on p.codigo = v.codigo;

-- Matérias com setor detectado mas impacto ainda não avaliado (fila de trabalho do analista)
create or replace view v_fila_classificacao as
select m.codigo, m.sigla || ' ' || m.numero || '/' || m.ano as materia, m.ementa,
       array_agg(ms.setor_id order by ms.setor_id) as setores,
       max(v.data_sessao) as ultima_votacao
from materia_setor ms
join materias m on m.codigo = ms.materia_codigo
left join votacoes v on v.materia_codigo = m.codigo
where ms.impacto is null
group by m.codigo
order by ultima_votacao desc nulls last;

-- Leitura pública (anon) para o front; escrita só via service role (ingestão)
alter table senadores      enable row level security;
alter table materias       enable row level security;
alter table votacoes       enable row level security;
alter table votos          enable row level security;
alter table setores        enable row level security;
alter table ativos         enable row level security;
alter table setor_palavras enable row level security;
alter table materia_setor  enable row level security;

do $$
declare t text;
begin
  foreach t in array array['senadores','materias','votacoes','votos','setores','ativos','setor_palavras','materia_setor'] loop
    if not exists (select 1 from pg_policies where tablename = t and policyname = 'leitura_publica') then
      execute format('create policy leitura_publica on %I for select using (true)', t);
    end if;
  end loop;
end $$;
