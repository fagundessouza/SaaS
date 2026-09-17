"""Importa todo modulo de modelo do dominio para garantir que Base.metadata esteja completo.

Necessario em qualquer processo que nao importe organicamente todos os modelos antes de usar o
ORM (Alembic, o worker Arq) — sem isso, SQLAlchemy nao consegue resolver ForeignKey entre tabelas
cujos modelos nunca foram importados naquele processo. A API nao precisa disso hoje porque seus
routers ja importam os modelos que usam, mas e mais seguro depender deste registro tambem la a
medida que o numero de dominios cresce (Fase 2+).
"""

from core.events import models as _events_models  # noqa: F401
from core.jobs import models as _jobs_models  # noqa: F401
from core.tenancy import models as _tenancy_models  # noqa: F401
