"""Memory sharing — scopes and metadata for controlling memory visibility.

Sharing scopes:
  - private:  Only the owner can access
  - project:  Visible to members of the associated project
  - team:     Visible to the owner's team/class
  - global:   Visible to all authorized users

Stored in Markdown front matter and mirrored in vector metadata.
"""

from enum import Enum
from pathlib import Path
from typing import Optional

import frontmatter
from pydantic import BaseModel, Field


class SharingScope(str, Enum):
    private = "private"
    project = "project"
    team = "team"
    global_ = "global"


class SharingMetadata(BaseModel):
    """Sharing configuration stored in Markdown front matter."""
    owner: str
    scope: SharingScope = SharingScope.private
    sensitivity: str = "normal"
    allowed_readers: list[str] = Field(default_factory=list)
    purpose_tags: list[str] = Field(default_factory=list)
    project_id: Optional[str] = None


def read_sharing_metadata(path: Path) -> SharingMetadata | None:
    """Read sharing metadata from a Markdown file's front matter."""
    if not path.exists():
        return None
    post = frontmatter.load(str(path))
    sharing = post.metadata.get("sharing")
    if sharing:
        return SharingMetadata.model_validate(sharing)
    # Fallback: construct from individual fields
    owner = post.metadata.get("owner") or post.metadata.get("user_id", "unknown")
    return SharingMetadata(
        owner=owner,
        scope=SharingScope(post.metadata.get("scope", "private")),
        sensitivity=post.metadata.get("sensitivity", "normal"),
    )


def write_sharing_metadata(path: Path, sharing: SharingMetadata):
    """Write or update sharing metadata in a Markdown file's front matter."""
    if path.exists():
        post = frontmatter.load(str(path))
    else:
        post = frontmatter.Post(content="")
        path.parent.mkdir(parents=True, exist_ok=True)

    post.metadata["sharing"] = sharing.model_dump(mode="json")
    path.write_text(frontmatter.dumps(post))


def check_access(sharing: SharingMetadata, reader_id: str, reader_projects: list[str] | None = None) -> bool:
    """Check if a reader has access to a memory based on sharing metadata."""
    # Owner always has access
    if reader_id == sharing.owner:
        return True

    # Global scope — everyone can access
    if sharing.scope == SharingScope.global_:
        return True

    # Explicit reader list
    if reader_id in sharing.allowed_readers:
        return True

    # Project scope — check project membership
    if sharing.scope == SharingScope.project and sharing.project_id:
        if reader_projects and sharing.project_id in reader_projects:
            return True

    # Team scope would check team membership (simplified for demo)
    if sharing.scope == SharingScope.team:
        # In a real system, check team membership via a team service
        if reader_id in sharing.allowed_readers:
            return True

    return False
