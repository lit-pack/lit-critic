"""
lit-critic - Server/Backend

Core analysis engine for the lit-critic system.
This package runs 5 analytical lenses in parallel, coordinates findings,
and provides the backend for CLI, Web, and VS Code frontends.
"""

__version__ = "0.1.0"

from .models import Finding, LensResult, SessionState, LearningData
from .config import MODEL, MAX_TOKENS, INDEX_FILES, OPTIONAL_FILES

__all__ = [
    "Finding",
    "LensResult", 
    "SessionState",
    "LearningData",
    "MODEL",
    "MAX_TOKENS",
    "INDEX_FILES",
    "OPTIONAL_FILES",
]
