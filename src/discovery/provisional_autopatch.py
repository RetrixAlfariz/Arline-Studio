from __future__ import annotations

from . import provisional
from . import service as service_module
from . import spatial as spatial_module
from .identity import install_identity_resolution
from .library_scope import install_library_scope_lineage
from .promotion import install_promotion_hardening
from .provisional_materialize import materialize_proposition_branch_aware
from .provisional_runtime import install_provisional_runtime_fix
from .semantics import install_claim_semantics
from .spatial_v2 import install_spatial_v2


# These two extensions must be installed before web.attach_discovery() binds the
# generic/spatial capture hooks. They only replace deterministic resolver
# functions; no store mutation happens at import time.
install_identity_resolution(service_module, provisional)
install_spatial_v2(spatial_module)


if not getattr(provisional, "_RUNTIME_FIX_WRAPPED", False):
    _original_install = provisional.install_provisional_discovery

    def _install_with_runtime_fix(service):
        # materialize_turn/materialize_existing resolve this module-global at
        # call time, so replace it before the original installer performs its
        # first existing-discovery projection.
        provisional._materialize_proposition = materialize_proposition_branch_aware
        _original_install(service)
        install_provisional_runtime_fix(service)
        install_library_scope_lineage(service)
        install_claim_semantics(service)
        install_promotion_hardening(service)

    provisional.install_provisional_discovery = _install_with_runtime_fix
    provisional._RUNTIME_FIX_WRAPPED = True
