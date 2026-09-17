"""Importa todo modulo de modelo do dominio para garantir que Base.metadata esteja completo.

Fica FORA de qualquer pacote em camadas (core/ai_platform/domains/api) de proposito: e o unico
modulo autorizado a importar modelos de todo bounded context, inclusive `domains.*`, o que
violaria o contrato de camadas se estivesse dentro de `core` (ver ADR-0001 e a mesma razao pela
qual `worker.py` existe como composition root fora de `core`).

Necessario em qualquer processo que nao importe organicamente todos os modelos antes de usar o
ORM (Alembic, o worker Arq). A API tambem importa isto por seguranca/consistencia, mesmo que
seus routers ja importem os modelos que usam diretamente.
"""

from ai_platform.documents import models as _document_models  # noqa: F401
from core.auth import models as _auth_models  # noqa: F401
from core.billing import models as _billing_models  # noqa: F401
from core.events import models as _events_models  # noqa: F401
from core.jobs import models as _jobs_models  # noqa: F401
from core.tenancy import models as _tenancy_models  # noqa: F401
from domains.procurement.companies import models as _company_models  # noqa: F401
from domains.procurement.opportunities import models as _opportunity_models  # noqa: F401
from domains.procurement.tenders import models as _tender_models  # noqa: F401
