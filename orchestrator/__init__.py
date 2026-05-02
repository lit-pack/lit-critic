"""Platform layer primitives for local orchestration over stateless Core."""

__version__ = "5.0.1"

from .core_client import CoreClient, CoreClientError, CoreClientHTTPError
from .facade import PlatformFacade
from .mappers import contract_to_finding, finding_to_contract

__all__ = [
    "__version__",
    "CoreClient",
    "CoreClientError",
    "CoreClientHTTPError",
    "PlatformFacade",
    "finding_to_contract",
    "contract_to_finding",
]
