from __future__ import annotations

from . import provisional
from .provisional_materialize import materialize_proposition_branch_aware
from .provisional_runtime import install_provisional_runtime_fix


if not getattr(provisional, "_RUNTIME_FIX_WRAPPED", False):
    _original_install = provisional.install_provisional_discovery

    def _install_with_runtime_fix(service):
        # materialize_turn/materialize_existing resolve this module-global at
        # call time, so replace it before the original installer performs its
        # first existing-discovery projection.
        provisional._materialize_proposition = materialize_proposition_branch_aware
        _original_install(service)
        install_provisional_runtime_fix(service)

    provisional.install_provisional_discovery = _install_with_runtime_fix
    provisional._RUNTIME_FIX_WRAPPED = True
