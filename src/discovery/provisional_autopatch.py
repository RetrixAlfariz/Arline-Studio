from __future__ import annotations

from . import performance as performance_module
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
from .startup import (
    deferred_materialization_report,
    install_combined_historical_drain,
    install_incremental_branch_repair,
    install_minimal_performance_schema,
)


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

        # Cache tables are cheap. Optional secondary indexes over historical
        # evidence are not a prerequisite for application readiness and therefore
        # are intentionally excluded from the startup critical path.
        install_minimal_performance_schema(performance_module, service)

        # Performance primitives wrap the complete semantic capture chain before
        # the provisional installer binds service methods.
        prepare_discovery_performance(
            service,
            provisional,
            provisional_runtime_module,
            physical_items_module,
        )
        install_incremental_branch_repair(provisional_runtime_module, service)

        # New/changed propositions are branch-aware from their first projection.
        provisional._materialize_proposition = materialize_proposition_branch_aware

        # The original installer historically scanned/materialized every existing
        # Discovery before returning. During initial attach we temporarily replace
        # that one global with a zero-I/O report. The service method it installs
        # resolves the module global at call time, so restoring the real function
        # immediately afterwards preserves explicit/backfill behavior.
        real_materialize_existing = provisional.materialize_existing

        def startup_materialize_existing(_service, *, limit: int = 5000):
            return deferred_materialization_report(provisional)

        provisional.materialize_existing = startup_materialize_existing
        try:
            _original_install(service)
        finally:
            provisional.materialize_existing = real_materialize_existing

        # Runtime branch hardening also used to scan all historical evidence as
        # soon as it was installed. Suppress only that installer-time sweep;
        # restore the incremental batch repair before any user/background call.
        real_repair_existing = provisional_runtime_module.repair_existing_branch_projections
        provisional_runtime_module.repair_existing_branch_projections = lambda *_args, **_kwargs: {
            "processed": 0,
            "pending": -1,
            "deferred": True,
        }
        try:
            install_provisional_runtime_fix(service)
        finally:
            provisional_runtime_module.repair_existing_branch_projections = real_repair_existing

        # Reinstall our capped historical repair after the runtime installer and
        # combine it with the bounded materialization drain used by backfill and
        # the daemon worker. Per-turn projection remains immediate.
        service._incremental_branch_repair_installed = False
        install_incremental_branch_repair(provisional_runtime_module, service)
        install_combined_historical_drain(provisional, service)

        install_library_scope_lineage(service)
        install_claim_semantics(service)
        install_promotion_hardening(service)

        # Query/list/resource caches are installed after every correctness and
        # scope wrapper so all fast paths preserve the final authority contract.
        finalize_discovery_performance(service)

    provisional.install_provisional_discovery = _install_with_runtime_fix
    provisional._RUNTIME_FIX_WRAPPED = True
