"""Domain exceptions for the publish pipeline.

These exceptions represent business-rule violations and are raised by domain
functions.  The API layer catches them and translates to HTTP responses
(e.g. HTTPException), keeping framework concerns out of the domain.
"""

from __future__ import annotations

from dataclasses import dataclass


class DomainError(Exception):
    """Base class for all domain exceptions."""


class ManifestParseError(DomainError):
    """SKILL.md manifest is malformed or unparseable."""


class EvalCaseParseError(DomainError):
    """Eval case YAML files are malformed."""


class EvalConfigError(DomainError):
    """Eval config declared but no matching case files found."""


class OrgNotFoundError(DomainError):
    """Organisation slug does not match any known org."""


class NotOrgMemberError(DomainError):
    """User is not a member of the organisation."""


class AdminRequiredError(DomainError):
    """Action requires org owner or admin role."""


@dataclass
class GauntletRejectionError(DomainError):
    """Skill was rejected by the gauntlet safety pipeline."""

    summary: str

    def __str__(self) -> str:
        return f"Gauntlet checks failed: {self.summary}"
