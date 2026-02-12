"""Domain models as frozen dataclasses."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

# Re-export shared models from dhub_core (single source of truth)
from dhub_core.models import (  # noqa: F401
    AgentTestTarget,
    DependencySpec,
    EvalConfig,
    RuntimeConfig,
    SkillManifest,
    TestingConfig,
)

# Status vocabularies — single source of truth for magic strings
CheckSeverity = Literal["pass", "warn", "fail"]
SafetyGrade = Literal["A", "B", "C", "F"]
EvalReportStatus = Literal["pending", "completed", "failed", "error"]
EvalRunStatus = Literal["pending", "provisioning", "running", "judging", "completed", "failed"]


@dataclass(frozen=True)
class User:
    id: UUID
    github_id: str
    username: str
    github_orgs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Organization:
    id: UUID
    slug: str
    owner_id: UUID
    is_personal: bool = False


@dataclass(frozen=True)
class OrgMember:
    org_id: UUID
    user_id: UUID
    role: str


@dataclass(frozen=True)
class Skill:
    id: UUID
    org_id: UUID
    name: str
    description: str
    download_count: int = 0
    category: str = ""
    visibility: str = "public"


@dataclass(frozen=True)
class SkillAccessGrant:
    id: UUID
    skill_id: UUID
    grantee_org_id: UUID
    granted_by: UUID
    created_at: datetime


@dataclass(frozen=True)
class Version:
    id: UUID
    skill_id: UUID
    semver: str
    s3_key: str
    checksum: str
    runtime_config: dict | None
    eval_status: str
    created_at: datetime | None = None
    published_by: str = ""


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int


@dataclass(frozen=True)
class AuthToken:
    access_token: str
    token_type: str = "bearer"


@dataclass(frozen=True)
class UserApiKey:
    id: UUID
    user_id: UUID
    key_name: str
    encrypted_value: bytes
    created_at: datetime


@dataclass(frozen=True)
class AgentSandboxConfig:
    """Configuration for running evals in a specific agent's sandbox."""

    npm_package: str
    skills_path: str
    run_cmd: tuple[str, ...]
    key_env_var: str
    extra_env: dict[str, str]


@dataclass(frozen=True)
class EvalCase:
    """A single evaluation case from evals/*.yaml."""

    name: str
    description: str
    prompt: str
    judge_criteria: str


@dataclass(frozen=True)
class EvalCaseResult:
    """Result of running and judging a single eval case."""

    name: str
    description: str
    verdict: str
    reasoning: str
    agent_output: str
    agent_stderr: str
    exit_code: int
    duration_ms: int
    stage: str


@dataclass(frozen=True)
class EvalReport:
    """Aggregated eval report for a skill version."""

    id: UUID
    version_id: UUID
    agent: str
    judge_model: str
    case_results: list[dict]
    passed: int
    total: int
    total_duration_ms: int
    status: EvalReportStatus
    error_message: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class EvalRun:
    """Operational state for a background eval job."""

    id: UUID
    version_id: UUID
    user_id: UUID
    agent: str
    judge_model: str
    status: EvalRunStatus
    stage: str | None
    current_case: str | None
    current_case_index: int | None
    total_cases: int
    heartbeat_at: datetime | None
    log_s3_prefix: str
    log_seq: int
    error_message: str | None
    created_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # prevent pytest from trying to collect this dataclass
    prompt: str
    assertions: tuple[dict, ...]


@dataclass(frozen=True)
class EvalResult:
    check_name: str
    severity: CheckSeverity
    message: str
    details: dict | None = None

    @property
    def passed(self) -> bool:
        return self.severity != "fail"


@dataclass(frozen=True)
class GauntletReport:
    results: tuple[EvalResult, ...]
    grade: SafetyGrade

    @property
    def passed(self) -> bool:
        return self.grade != "F"

    @property
    def summary(self) -> str:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        return f"Grade {self.grade}: {passed}/{total} checks passed"


@dataclass(frozen=True)
class AuditLogEntry:
    id: UUID
    org_slug: str
    skill_name: str
    semver: str
    grade: str
    version_id: UUID | None
    check_results: list[dict]
    llm_reasoning: dict | None
    publisher: str
    quarantine_s3_key: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class SkillTracker:
    """Tracks a GitHub repo for automatic skill republishing."""

    id: UUID
    user_id: UUID
    org_slug: str
    repo_url: str
    branch: str
    last_commit_sha: str | None
    poll_interval_minutes: int
    enabled: bool
    last_checked_at: datetime | None
    last_published_at: datetime | None
    last_error: str | None
    created_at: datetime | None


@dataclass(frozen=True)
class SkillIndexEntry:
    """Entry in the search index."""

    org_slug: str
    skill_name: str
    description: str
    latest_version: str
    eval_status: str
    trust_score: str
    author: str = ""
    category: str = ""
