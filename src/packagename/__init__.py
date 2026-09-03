"""PACKAGENAME: Machine Learning project with a medallion ETL pipeline.

Only lightweight, dependency-free names are re-exported here. Heavier modules
(``tracking`` pulls in W&B, ``viz`` pulls in Matplotlib) are imported explicitly
by the code that needs them, so ``import packagename`` stays fast.
"""

from importlib.metadata import PackageNotFoundError, version

from packagename.config import PROJECT_ROOT, Settings, get_settings, load_settings
from packagename.log import get_logger, setup_logging
from packagename.seed import set_seed

try:
    __version__ = version("packagename")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0.dev0"

__all__ = [
    "PROJECT_ROOT",
    "Settings",
    "__version__",
    "get_logger",
    "get_settings",
    "load_settings",
    "set_seed",
    "setup_logging",
]
