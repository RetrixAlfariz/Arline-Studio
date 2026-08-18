from __future__ import annotations

from . import physical_item_refinement as physical_refinement_module
from . import physical_items as physical_items_module
from . import provisional
from . import provisional_runtime as provisional_runtime_module
from . import service as service_module
from . import spatial as spatial_module
from .garment import install_garment_materialization, install_garment_runtime
from .identity import install_identity_resolution
from .library_scope import install_library_scope_lineage
from .performance import finalize_discovery_performance, prepare_discovery_performance
from .physical_item_ambiguity import install_physical_item_ambiguity_guard
from .physical_item_merge import install_safe_anaphora_merge
from .physical_item_refinement import install_physical_item_refinement
from .physical_items import install_physical_item_identity
from .promotion import install_promotion_hardening
from .provisional_materialize import materialize_proposition_branch_aware
from .provisional_runtime import install_provisional_runtime_fix
from .semantics import install_claim_semantics
from .spatial_v2 import install_spatial_v2


# These extensions must be installed before web.attach_discovery() binds the
# capture/materialization hooks. They replace deterministic resolver adapters;
# no source truth is mutated at import time.
install_identity_resolution(service_module, provisional)
install_spatial_v2(spatial_module)
install_garment_materialization(provisional)
install_safe_anaphora_merge(physical_refinement_module)


if not getattr(provisional, "_RUNTIME_FIX_WRAPPED", False):
    _original_install = provisional.install_provisional_discovery

    def _install_with_runtime_fix(service):
        # Preserve semantic garment paths, resolve repeatable garment classes
        # into stable physical ITEM identities, repair explicit anaphora, and
        # block ambiguous references from falling back to legacy type identities.
        install_garment_runtime(service)
        install_physical_item_identity(service)
        install_physical_item_refinement(service)
        install_physical_item_ambiguity_guard(service)

        # Performance primitives must wrap the complete semantic capture chain,
        # but must be installed before provisional startup projection runs. This
        # turns full analytical re-runs and global materialization scans into
        # revision-aware, bounded incremental work without weakening provenance.
        prepare_discovery_performance(
            service,
            provisional,
            provisional_runtime_module,
            physical_items_module,
        )

        # materialize_turn/materialize_existing resolve this module-global at
        # call time, so replace it before the original installer performs its
        # first existing-discovery projection.
        provisional._materialize_proposition = materialize_proposition_branch_aware
        _original_install(service)
        install_provisional_runtime_fix(service)
        install_library_scope_lineage(service)
        install_claim_semantics(service)
        install_promotion_hardening(service)

        # Query/list/resource caches are installed after every correctness and
        # scope wrapper so all fast paths preserve the final authority contract.
        finalize_discovery_performance(service)

    provisional.install_provisional_discovery = _install_with_runtime_fix
    provisional._RUNTIME_FIX_WRAPPED = True
