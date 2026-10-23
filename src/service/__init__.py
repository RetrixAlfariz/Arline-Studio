from .arline_service import ArlineService, AnalysisBundle, GenerationBundle
from .artifacts import ArtifactStore, SavedRun, make_run_id
from .v121_rails import install_v121_service

# Character Rails are writer-only steering. Install before StreamingArlineService
# is imported so both normal and streamed generation see the same service API.
install_v121_service()

__all__=["ArlineService","AnalysisBundle","GenerationBundle","ArtifactStore","SavedRun","make_run_id"]

from .streaming import StreamingArlineService
