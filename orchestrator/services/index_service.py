"""Index service.

All functions previously in this module have been removed:

- ``get_finding_index_context`` read physical CAST.md / GLOSSARY.md from disk via
  ``_extract_index_entries``.  Those files no longer exist on disk (knowledge is now
  stored in SQLite).  The function was never wired into any API route or UI and always
  returned empty results.  Removed together with its helpers
  ``_normalize_index_coverage_scopes``, ``_extract_index_entries``, and
  ``_entry_reference_pattern``.

The author-maintained index files that still exist on disk (CANON.md, STYLE.md) are
handled by ``index_projection_service.py``.
"""
