"""Data classes for the GitHub skills crawler."""

from dataclasses import dataclass, field


@dataclass
class DiscoveredRepo:
    """A GitHub repository discovered during the crawl."""

    full_name: str
    owner_login: str
    owner_type: str  # "User" or "Organization"
    clone_url: str
    stars: int = 0
    description: str = ""


@dataclass
class CrawlStats:
    """Aggregate statistics for a crawl run."""

    queries_made: int = 0
    repos_discovered: int = 0
    repos_processed: int = 0
    repos_skipped_checkpoint: int = 0
    skills_published: int = 0
    skills_skipped: int = 0
    skills_failed: int = 0
    skills_quarantined: int = 0
    orgs_created: int = 0
    metadata_synced: int = 0
    errors: list[str] = field(default_factory=list)

    def accumulate(self, result: dict) -> None:
        """Accumulate counts from a single repo processing result."""
        self.repos_processed += 1
        self.skills_published += result.get("skills_published", 0)
        self.skills_skipped += result.get("skills_skipped", 0)
        self.skills_failed += result.get("skills_failed", 0)
        self.skills_quarantined += result.get("skills_quarantined", 0)
        if result.get("org_created"):
            self.orgs_created += 1
        if result.get("metadata_synced"):
            self.metadata_synced += 1
        if result.get("error"):
            self.errors.append(f"{result['repo']}: {result['error']}")


def repo_to_dict(repo: DiscoveredRepo) -> dict:
    """Serialize a DiscoveredRepo to a dict for Modal transport."""
    return {
        "full_name": repo.full_name,
        "owner_login": repo.owner_login,
        "owner_type": repo.owner_type,
        "clone_url": repo.clone_url,
        "stars": repo.stars,
        "description": repo.description,
    }


def dict_to_repo(d: dict) -> DiscoveredRepo:
    """Deserialize a dict back to a DiscoveredRepo."""
    return DiscoveredRepo(
        full_name=d["full_name"],
        owner_login=d["owner_login"],
        owner_type=d["owner_type"],
        clone_url=d["clone_url"],
        stars=d.get("stars", 0),
        description=d.get("description", ""),
    )
