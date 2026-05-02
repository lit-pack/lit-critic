"""v1 contract schemas and compatibility adapters."""

__version__ = "3.0.0"

from .adapters import (
    adapt_analyze_request_to_legacy,
    adapt_discuss_request_to_legacy,
    adapt_legacy_analyze_output_to_response,
    adapt_legacy_discuss_output_to_response,
    adapt_legacy_re_evaluate_output_to_response,
)
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    DiscussAction,
    DiscussRequest,
    DiscussResponse,
    FindingContract,
    IndexesContract,
    MetaContract,
    ReEvaluateFindingRequest,
    ReEvaluateFindingResponse,
)
from .wrappers import (
    run_analyze_contract_compatible,
    to_discuss_contract_response,
    to_re_evaluate_contract_response,
)

__all__ = [
    "__version__",
    "AnalyzeRequest",
    "AnalyzeResponse",
    "DiscussAction",
    "DiscussRequest",
    "DiscussResponse",
    "FindingContract",
    "IndexesContract",
    "MetaContract",
    "ReEvaluateFindingRequest",
    "ReEvaluateFindingResponse",
    "adapt_analyze_request_to_legacy",
    "adapt_discuss_request_to_legacy",
    "adapt_legacy_analyze_output_to_response",
    "adapt_legacy_discuss_output_to_response",
    "adapt_legacy_re_evaluate_output_to_response",
    "run_analyze_contract_compatible",
    "to_discuss_contract_response",
    "to_re_evaluate_contract_response",
]
