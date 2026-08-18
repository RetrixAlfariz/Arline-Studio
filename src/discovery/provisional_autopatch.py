from __future__ import annotations

from . import provisional
from .provisional_runtime import install_provisional_runtime_fix


if not getattr(provisional, "_RUNTIME_FIX_WRAPPED", False):
    _original_install = provisional.install_provisional_discovery

    def _install_with_runtime_fix(service):
        _original_install(service)
        install_provisional_runtime_fix(service)

    provisional.install_provisional_discovery = _install_with_runtime_fix
    provisional._RUNTIME_FIX_WRAPPED = True
