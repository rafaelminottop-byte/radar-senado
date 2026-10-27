-- Seed inicial: setores, palavras-chave e tickers de referência.
-- É um ponto de partida para editar, não uma cobertura completa da B3.

insert into setores (id, nome) values
  ('bancos',          'Bancos e crédito'),
  ('seguros',         'Seguros e previdência'),
  ('mercado_capitais','Mercado de capitais, dividendos e fundos'),
  ('eletricas',       'Energia elétrica'),
  ('saneamento',      'Saneamento'),
  ('petroleo',        'Petróleo, gás e combustíveis'),
  ('mineracao',       'Mineração e siderurgia'),
  ('agro',            'Agronegócio e proteína animal'),
  ('varejo',          'Varejo e consumo'),
  ('saude',           'Saúde e planos de saúde'),
  ('educacao',        'Educação'),
  ('construcao',      'Construção e imobiliário'),
  ('telecom',         'Telecomunicações'),
  ('trabalho',        'Custo de mão de obra (transversal)')
on conflict (id) do nothing;

insert into setor_palavras (setor_id, termo) values
  ('bancos','instituicao financeira'), ('bancos','instituicoes financeiras'), ('bancos','credito'),
  ('bancos','taxa de juros'), ('bancos','limite de juros'), ('bancos','cartao de credito'), ('bancos','rotativo'), ('bancos','banco central'),
  ('bancos','consignado'), ('bancos','spread'), ('bancos','csll'),
  ('seguros','seguro'), ('seguros','seguradora'), ('seguros','previdencia complementar'), ('seguros','resseguro'),
  ('mercado_capitais','dividendo'), ('mercado_capitais','juros sobre capital proprio'), ('mercado_capitais','jcp'),
  ('mercado_capitais','fundos de investimento'), ('mercado_capitais','fundo imobiliario'), ('mercado_capitais','fii'),
  ('mercado_capitais','fiagro'), ('mercado_capitais','lci'), ('mercado_capitais','lca'), ('mercado_capitais','debenture'),
  ('mercado_capitais','valores mobiliarios'), ('mercado_capitais','imposto de renda'), ('mercado_capitais','aplicacoes financeiras'),
  ('eletricas','energia eletrica'), ('eletricas','setor eletrico'), ('eletricas','aneel'), ('eletricas','tarifa de energia'),
  ('eletricas','geracao distribuida'), ('eletricas','transmissao de energia'), ('eletricas','distribuidoras de energia'),
  ('eletricas','eletrobras'), ('eletricas','mercado livre de energia'),
  ('saneamento','saneamento'), ('saneamento','agua e esgoto'), ('saneamento','esgotamento sanitario'), ('saneamento','residuos solidos'),
  ('petroleo','petroleo'), ('petroleo','gas natural'), ('petroleo','combustive'), ('petroleo','petrobras'),
  ('petroleo','royalties'), ('petroleo','biocombustive'), ('petroleo','etanol'), ('petroleo','diesel'),
  ('mineracao','mineracao'), ('mineracao','minerio'), ('mineracao','cfem'), ('mineracao','siderurg'),
  ('agro','agropecuari'), ('agro','agronegocio'), ('agro','produtor rural'), ('agro','defensivos'), ('agro','agrotoxico'),
  ('agro','credito rural'), ('agro','plano safra'), ('agro','frigorifico'), ('agro','carne'), ('agro','licenciamento ambiental'),
  ('agro','marco temporal'), ('agro','funrural'),
  ('varejo','varejo'), ('varejo','comercio eletronico'), ('varejo','importacao'), ('varejo','remessa internacional'),
  ('varejo','consumidor'), ('varejo','ipi'),
  ('saude','plano de saude'), ('saude','planos de saude'), ('saude','ans'), ('saude','medicamento'), ('saude','hospita'),
  ('educacao','ensino superior'), ('educacao','fies'), ('educacao','prouni'), ('educacao','ensino a distancia'),
  ('construcao','habitacional'), ('construcao','minha casa'), ('construcao','imobiliari'), ('construcao','construcao civil'),
  ('construcao','incorporacao'), ('construcao','financiamento habitacional'),
  ('telecom','telecomunica'), ('telecom','anatel'), ('telecom','espectro'), ('telecom','fust'),
  ('trabalho','jornada de trabalho'), ('trabalho','escala 6x1'), ('trabalho','salario minimo'), ('trabalho','desoneracao da folha'),
  ('trabalho','folha de pagamento'), ('trabalho','clt'), ('trabalho','terceirizacao')
on conflict do nothing;

insert into ativos (ticker, empresa, setor_id) values
  ('ITUB4','Itaú Unibanco','bancos'), ('BBDC4','Bradesco','bancos'), ('BBAS3','Banco do Brasil','bancos'),
  ('SANB11','Santander Brasil','bancos'), ('BPAC11','BTG Pactual','bancos'),
  ('BBSE3','BB Seguridade','seguros'), ('PSSA3','Porto Seguro','seguros'),
  ('B3SA3','B3','mercado_capitais'),
  ('ELET3','Eletrobras','eletricas'), ('EQTL3','Equatorial','eletricas'), ('CPLE6','Copel','eletricas'),
  ('EGIE3','Engie Brasil','eletricas'), ('TAEE11','Taesa','eletricas'),
  ('SBSP3','Sabesp','saneamento'), ('CSMG3','Copasa','saneamento'), ('SAPR11','Sanepar','saneamento'),
  ('PETR4','Petrobras','petroleo'), ('PRIO3','PRIO','petroleo'), ('VBBR3','Vibra','petroleo'), ('UGPA3','Ultrapar','petroleo'),
  ('VALE3','Vale','mineracao'), ('GGBR4','Gerdau','mineracao'),
  ('SLCE3','SLC Agrícola','agro'), ('SMTO3','São Martinho','agro'), ('MBRF3','MBRF','agro'),
  ('MGLU3','Magazine Luiza','varejo'), ('LREN3','Lojas Renner','varejo'),
  ('RDOR3','Rede D''Or','saude'), ('HAPV3','Hapvida','saude'),
  ('COGN3','Cogna','educacao'), ('YDUQ3','Yduqs','educacao'),
  ('CYRE3','Cyrela','construcao'), ('MRVE3','MRV','construcao'),
  ('VIVT3','Vivo','telecom'), ('TIMS3','TIM','telecom')
on conflict (ticker) do nothing;
