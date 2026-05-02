"""Mapping helpers between legacy server models and v1 contracts."""

from __future__ import annotations

from contracts.v1.schemas import FindingContract
from orchestrator.runtime.models import Finding


def finding_to_contract(finding: Finding) -> FindingContract:
    """Convert a legacy ``Finding`` to a v1 ``FindingContract``."""
    return FindingContract.model_validate(finding.to_dict(include_state=False))


def contract_to_finding(contract: FindingContract) -> Finding:
    """Convert a v1 ``FindingContract`` to a legacy ``Finding``."""
    return Finding.from_dict(contract.model_dump())
