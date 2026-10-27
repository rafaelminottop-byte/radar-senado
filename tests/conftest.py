"""Configuração dos testes.

Os testes exercitam as funções puras e a lógica de ingestão de `ingest/ingest.py`
sem precisar de um Postgres. O módulo importa `psycopg` no topo (driver de banco),
então criamos um stub mínimo antes de importá-lo. `requests` é importado também, mas
está instalado e os testes nunca chamam a rede.
"""

import sys
import types
from pathlib import Path

# ingest/ no sys.path para `import ingest`
INGEST_DIR = Path(__file__).resolve().parent.parent / "ingest"
sys.path.insert(0, str(INGEST_DIR))

# Stub de psycopg: só para o import funcionar sem o driver instalado.
if "psycopg" not in sys.modules:
    psycopg = types.ModuleType("psycopg")
    psycopg.Connection = object
    psycopg.Cursor = object

    def _sem_banco(*_a, **_k):  # pragma: no cover - só dispara se um teste tentar conectar
        raise RuntimeError("psycopg stub: os testes não acessam banco")

    psycopg.connect = _sem_banco
    sys.modules["psycopg"] = psycopg

    sys.modules["psycopg.types"] = types.ModuleType("psycopg.types")
    json_mod = types.ModuleType("psycopg.types.json")
    json_mod.Jsonb = lambda x: x  # identidade: guardamos o dict cru da votação
    sys.modules["psycopg.types.json"] = json_mod
