"""Domain tree index — persisted as INDEX.md alongside other documents.

A derived, rebuildable index that organizes sections into a hierarchical
domain tree. Each node aggregates statistics from its children.

INDEX.md sits alongside AGENTS.md, SOUL.md, etc. It is:
- Human-readable: renders as a Markdown document with ASCII tree + rollup tables
- Machine-readable: YAML front matter contains the full tree structure
- Derived: can be rebuilt from the other documents at any time
- Auto-updated: rebuilt whenever sections are created, updated, or deleted
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter

from app.models import Section, SectionKind, SectionStatus, utcnow

MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", "memory"))


@dataclass
class TreeNode:
    """A node in the domain tree."""
    name: str
    path: str
    children: dict[str, TreeNode] = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)

    # Rollup stats
    total_sections: int = 0
    mastery_avg: Optional[float] = None
    mastery_scores: dict[str, float] = field(default_factory=dict)
    confidence_avg: Optional[float] = None
    error_pattern_count: int = 0
    inference_count: int = 0
    interaction_event_count: int = 0
    kinds_present: set[str] = field(default_factory=set)
    latest_update: Optional[str] = None

    def to_dict(self, depth: int = -1) -> dict:
        result = {
            "name": self.name,
            "path": self.path,
            "total_sections": self.total_sections,
            "kinds_present": sorted(self.kinds_present),
            "latest_update": self.latest_update,
        }
        if self.mastery_avg is not None:
            result["mastery_avg"] = round(self.mastery_avg, 3)
            result["mastery_scores"] = self.mastery_scores
        if self.confidence_avg is not None:
            result["confidence_avg"] = round(self.confidence_avg, 3)
        if self.error_pattern_count:
            result["error_pattern_count"] = self.error_pattern_count
        if self.inference_count:
            result["inference_count"] = self.inference_count
        if self.interaction_event_count:
            result["interaction_event_count"] = self.interaction_event_count

        result["sections"] = [
            {
                "id": s.id,
                "heading": s.heading,
                "kind": s.kind.value,
                "document": s.document.value,
                "domain_path": s.domain_path,
                "confidence": s.confidence,
            }
            for s in self.sections
        ]

        if depth != 0 and self.children:
            child_depth = depth - 1 if depth > 0 else -1
            result["children"] = {
                name: child.to_dict(depth=child_depth)
                for name, child in sorted(self.children.items())
            }
        elif self.children:
            result["child_count"] = len(self.children)
            result["child_names"] = sorted(self.children.keys())

        return result

    def to_ascii(self, prefix: str = "", is_last: bool = True) -> str:
        connector = "└── " if is_last else "├── "
        label = self.name
        stats = []
        if self.mastery_avg is not None:
            stats.append(f"mastery={self.mastery_avg:.2f}")
        if self.total_sections:
            stats.append(f"sections={self.total_sections}")
        if self.error_pattern_count:
            stats.append(f"errors={self.error_pattern_count}")
        if stats:
            label += f"  ({', '.join(stats)})"

        lines = [f"{prefix}{connector}{label}"]
        child_prefix = prefix + ("    " if is_last else "│   ")
        children = sorted(self.children.values(), key=lambda c: c.name)
        for i, child in enumerate(children):
            lines.append(child.to_ascii(child_prefix, i == len(children) - 1))
        return "\n".join(lines)


def _ensure_path(root: TreeNode, path: str) -> TreeNode:
    parts = [p for p in path.strip("/").split("/") if p]
    current = root
    current_path = ""
    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part
        if part not in current.children:
            current.children[part] = TreeNode(name=part, path=current_path)
        current = current.children[part]
    return current


def _collect_all_sections(node: TreeNode) -> list[Section]:
    result = list(node.sections)
    for child in node.children.values():
        result.extend(_collect_all_sections(child))
    return result


def _rollup(node: TreeNode):
    for child in node.children.values():
        _rollup(child)

    all_sections = list(node.sections)
    for child in node.children.values():
        all_sections.extend(_collect_all_sections(child))

    active = [s for s in all_sections if s.status == SectionStatus.active]
    node.total_sections = len(active)

    if not active:
        return

    node.kinds_present = {s.kind.value for s in active}

    confidences = [s.confidence for s in active]
    node.confidence_avg = sum(confidences) / len(confidences)

    mastery_sections = [s for s in active if s.kind == SectionKind.mastery]
    if mastery_sections:
        node.mastery_scores = {s.heading: s.confidence for s in mastery_sections}
        node.mastery_avg = sum(s.confidence for s in mastery_sections) / len(mastery_sections)

    node.error_pattern_count = sum(1 for s in active if s.kind == SectionKind.error_pattern)
    node.inference_count = sum(1 for s in active if s.kind == SectionKind.inference)
    node.interaction_event_count = sum(1 for s in active if s.kind == SectionKind.interaction_event)

    timestamps = [s.updated_at.isoformat() for s in active if s.updated_at]
    if timestamps:
        node.latest_update = max(timestamps)


# --- Build from sections ---


def _build_from_sections(subject: str, all_sections: list[Section]) -> TreeNode:
    root = TreeNode(name=subject, path="")
    for section in all_sections:
        if section.status == SectionStatus.deleted:
            continue
        node = _ensure_path(root, section.domain_path)
        node.sections.append(section)
    _rollup(root)
    return root


# --- Render INDEX.md ---


def _render_node_table(node: TreeNode, indent: int = 0) -> list[str]:
    """Render a node as a markdown table row with indentation."""
    lines = []
    prefix = "&nbsp;" * (indent * 4) if indent else ""
    name = f"**{node.name}/**" if node.children else node.name

    mastery = f"{node.mastery_avg:.2f}" if node.mastery_avg is not None else "—"
    conf = f"{node.confidence_avg:.2f}" if node.confidence_avg is not None else "—"
    errors = str(node.error_pattern_count) if node.error_pattern_count else "—"
    events = str(node.interaction_event_count) if node.interaction_event_count else "—"
    inferences = str(node.inference_count) if node.inference_count else "—"

    lines.append(
        f"| {prefix}{name} | {node.total_sections} | {mastery} | {conf} | {errors} | {inferences} | {events} |"
    )

    for child in sorted(node.children.values(), key=lambda c: c.name):
        lines.extend(_render_node_table(child, indent + 1))
    return lines


def _render_index_markdown(subject: str, root: TreeNode) -> str:
    """Render the full INDEX.md content."""
    lines = ["# INDEX", ""]
    lines.append("> Derived domain tree index — rebuilt from canonical documents")
    lines.append(f"> Subject: {subject}")
    lines.append("")

    # ASCII tree
    lines.append("## Domain Tree")
    lines.append("")
    lines.append("```")
    lines.append(f"{root.name}  (total={root.total_sections})")
    children = sorted(root.children.values(), key=lambda c: c.name)
    for i, child in enumerate(children):
        lines.append(child.to_ascii("", i == len(children) - 1))
    lines.append("```")
    lines.append("")

    # Rollup table
    lines.append("## Rollup Statistics")
    lines.append("")
    lines.append("| Domain | Sections | Mastery | Confidence | Errors | Inferences | Events |")
    lines.append("|--------|----------|---------|------------|--------|------------|--------|")
    for child in sorted(root.children.values(), key=lambda c: c.name):
        lines.extend(_render_node_table(child))
    lines.append("")

    # Mastery summary
    mastery_sections = []
    for sec in _collect_all_sections(root):
        if sec.kind == SectionKind.mastery and sec.status == SectionStatus.active:
            mastery_sections.append(sec)
    if mastery_sections:
        mastery_sections.sort(key=lambda s: s.confidence, reverse=True)
        lines.append("## Mastery Summary")
        lines.append("")
        for s in mastery_sections:
            bar_len = int(s.confidence * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"- **{s.heading}** ({s.domain_path}): `{bar}` {s.confidence:.2f}")
        lines.append("")
        if root.mastery_avg is not None:
            bar_len = int(root.mastery_avg * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"**Overall mastery: `{bar}` {root.mastery_avg:.2f}**")
            lines.append("")

    # Error patterns
    error_sections = [
        s for s in _collect_all_sections(root)
        if s.kind == SectionKind.error_pattern and s.status == SectionStatus.active
    ]
    if error_sections:
        lines.append("## Active Error Patterns")
        lines.append("")
        for s in error_sections:
            lines.append(f"- **{s.heading}** (`{s.domain_path}`, confidence={s.confidence:.2f})")
            preview = s.content[:120].replace("\n", " ")
            lines.append(f"  {preview}...")
        lines.append("")

    # Domain paths
    paths = []
    def _walk(node):
        if node.sections:
            paths.append(node.path or "/")
        for child in node.children.values():
            _walk(child)
    _walk(root)

    lines.append("## All Domain Paths")
    lines.append("")
    for p in sorted(paths):
        lines.append(f"- `{p}`")
    lines.append("")

    return "\n".join(lines)


# --- Persistence ---


def _index_path(subject: str) -> Path:
    d = MEMORY_ROOT / "subjects" / subject
    d.mkdir(parents=True, exist_ok=True)
    return d / "INDEX.md"


def save_index(subject: str, root: TreeNode):
    """Persist the tree index as INDEX.md."""
    tree_data = root.to_dict(depth=-1)
    post = frontmatter.Post(
        content=_render_index_markdown(subject, root),
        subject=subject,
        document="INDEX",
        rebuilt_at=utcnow().isoformat(),
        total_sections=root.total_sections,
        mastery_avg=round(root.mastery_avg, 3) if root.mastery_avg is not None else None,
        tree=tree_data,
    )
    _index_path(subject).write_text(frontmatter.dumps(post))


def load_index(subject: str) -> dict | None:
    """Load the tree structure from INDEX.md front matter."""
    path = _index_path(subject)
    if not path.exists():
        return None
    post = frontmatter.load(str(path))
    return post.metadata.get("tree")


def load_index_markdown(subject: str) -> str | None:
    """Load the rendered markdown content of INDEX.md."""
    path = _index_path(subject)
    if not path.exists():
        return None
    post = frontmatter.load(str(path))
    return post.content


# --- Public API ---


def rebuild_index(subject: str, all_sections: list[Section]) -> TreeNode:
    """Rebuild the tree from sections and persist as INDEX.md."""
    root = _build_from_sections(subject, all_sections)
    save_index(subject, root)
    return root


def build_tree(subject: str) -> TreeNode:
    """Build the tree by scanning all sections and persist INDEX.md."""
    from app.store import list_sections
    all_sections = list_sections(subject)
    return rebuild_index(subject, all_sections)


def query_subtree(subject: str, path: str) -> TreeNode | None:
    root = build_tree(subject)
    if not path or path == "/":
        return root
    parts = [p for p in path.strip("/").split("/") if p]
    current = root
    for part in parts:
        if part not in current.children:
            return None
        current = current.children[part]
    return current


def list_paths(subject: str) -> list[str]:
    root = build_tree(subject)
    paths = []
    def _walk(node):
        if node.sections:
            paths.append(node.path or "/")
        for child in node.children.values():
            _walk(child)
    _walk(root)
    return sorted(paths)
