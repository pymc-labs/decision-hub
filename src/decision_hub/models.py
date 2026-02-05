"""Domain models as frozen dataclasses."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class User:
    id: UUID
    github_id: str
    username: str


@dataclass(frozen=True)
class Organization:
    id: UUID
    slug: str
    owner_id: UUID


@dataclass(frozen=True)
class OrgMember:
    org_id: UUID
    user_id: UUID
    role: str


@dataclass(frozen=True)
class OrgInvite:
    id: UUID
    org_id: UUID
    invitee_github_username: str
    status: str


@dataclass(frozen=True)
class Skill:
    id: UUID
    org_id: UUID
    name: str


@dataclass(frozen=True)
class Version:
    id: UUID
    skill_id: UUID
    semver: str
    s3_key: str
    checksum: str
    runtime_config: dict | None
    eval_status: str


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
class SkillManifest:
    """Parsed SKILL.md content."""
    name: str
    description: str
    license: str | None
    compatibility: str | None
    metadata: dict[str, str] | None
    allowed_tools: str | None
    runtime: "RuntimeConfig | None"
    testing: "TestingConfig | None"
    body: str


@dataclass(frozen=True)
class RuntimeConfig:
    driver: str
    entrypoint: str
    lockfile: str
    env: tuple[str, ...]


@dataclass(frozen=True)
class AgentTestTarget:
    name: str
    required_keys: tuple[str, ...]


@dataclass(frozen=True)
class TestingConfig:
    __test__ = False  # prevent pytest from trying to collect this dataclass
    cases: str
    agents: tuple[AgentTestTarget, ...]


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # prevent pytest from trying to collect this dataclass
    prompt: str
    assertions: tuple[dict, ...]


@dataclass(frozen=True)
class EvalResult:
    check_name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class GauntletReport:
    results: tuple[EvalResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def summary(self) -> str:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        status = "PASSED" if self.passed else "FAILED"
        return f"{status}: {passed}/{total} checks passed"


@dataclass(frozen=True)
class SkillIndexEntry:
    """Entry in the search index."""
    org_slug: str
    skill_name: str
    description: str
    latest_version: str
    eval_status: str
    trust_score: str
