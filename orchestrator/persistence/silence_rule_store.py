"""Persistence layer for SilenceRule (Task C2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from core.domain import SilenceRule
from orchestrator.persistence.path_utils import to_absolute, to_relative


class SilenceRuleStore:
    """CRUD operations for the ``silence_rule`` table."""

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        rule: SilenceRule,
        project_path: Path | None = None,
    ) -> int:
        """Persist a new silence rule and return its DB id.

        ``rule.id`` is updated in-place on the passed object.
        """
        stored_path = (
            to_relative(project_path, rule.scene_path)
            if rule.scene_path and project_path
            else rule.scene_path
        )
        cur = conn.execute(
            """INSERT INTO silence_rule
               (rule_type, scope, scene_path, finding_id, lens, severity,
                text_pattern, note, suspended, created_at, suspended_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.rule_type,
                rule.scope,
                stored_path,
                rule.finding_id,
                rule.lens,
                rule.severity,
                rule.text_pattern,
                rule.note,
                int(rule.suspended),
                rule.created_at,
                rule.suspended_at,
            ),
        )
        rule.id = cur.lastrowid  # type: ignore[assignment]
        conn.commit()
        return rule.id  # type: ignore[return-value]

    @staticmethod
    def update_suspended(
        conn: sqlite3.Connection,
        rule_id: int,
        suspended: bool,
        suspended_at: str = "",
    ) -> None:
        """Set the suspended flag on a rule."""
        conn.execute(
            "UPDATE silence_rule SET suspended = ?, suspended_at = ? WHERE id = ?",
            (int(suspended), suspended_at, rule_id),
        )
        conn.commit()

    @staticmethod
    def delete(conn: sqlite3.Connection, rule_id: int) -> None:
        """Permanently delete a silence rule."""
        conn.execute("DELETE FROM silence_rule WHERE id = ?", (rule_id,))
        conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @staticmethod
    def get(
        conn: sqlite3.Connection,
        rule_id: int,
        project_path: Path | None = None,
    ) -> Optional[SilenceRule]:
        """Load a single silence rule by id."""
        row = conn.execute(
            "SELECT * FROM silence_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
        if row is None:
            return None
        return SilenceRuleStore._row_to_rule(row, project_path=project_path)

    @staticmethod
    def list_for_scene(
        conn: sqlite3.Connection,
        scene_path: str,
        project_path: Path | None = None,
        *,
        include_suspended: bool = False,
    ) -> list[SilenceRule]:
        """Return rules scoped to *scene_path* (not project-wide rules).

        Args:
            include_suspended: if False (default), exclude suspended rules.
        """
        rel_path = (
            to_relative(project_path, scene_path)
            if project_path else scene_path
        )
        sql = "SELECT * FROM silence_rule WHERE scope = 'scene' AND scene_path = ?"
        params: list = [rel_path]
        if not include_suspended:
            sql += " AND suspended = 0"
        rows = conn.execute(sql, params).fetchall()
        return [SilenceRuleStore._row_to_rule(r, project_path=project_path) for r in rows]

    @staticmethod
    def list_project_wide(
        conn: sqlite3.Connection,
        project_path: Path | None = None,
        *,
        include_suspended: bool = False,
    ) -> list[SilenceRule]:
        """Return all project-scope rules.

        Args:
            include_suspended: if False (default), exclude suspended rules.
        """
        sql = "SELECT * FROM silence_rule WHERE scope = 'project'"
        if not include_suspended:
            sql += " AND suspended = 0"
        rows = conn.execute(sql).fetchall()
        return [SilenceRuleStore._row_to_rule(r, project_path=project_path) for r in rows]

    @staticmethod
    def list_applicable(
        conn: sqlite3.Connection,
        scene_path: str,
        project_path: Path | None = None,
    ) -> list[SilenceRule]:
        """Return all active rules that could apply to findings in *scene_path*.

        Combines: scene-scoped rules for this scene + all project-wide rules.
        Suspended rules are excluded.
        """
        scene_rules = SilenceRuleStore.list_for_scene(
            conn, scene_path, project_path=project_path
        )
        project_rules = SilenceRuleStore.list_project_wide(
            conn, project_path=project_path
        )
        return scene_rules + project_rules

    @staticmethod
    def list_all(
        conn: sqlite3.Connection,
        project_path: Path | None = None,
        *,
        include_suspended: bool = True,
    ) -> list[SilenceRule]:
        """Return every silence rule (for management UI)."""
        sql = "SELECT * FROM silence_rule ORDER BY created_at DESC"
        if not include_suspended:
            sql = (
                "SELECT * FROM silence_rule WHERE suspended = 0 ORDER BY created_at DESC"
            )
        rows = conn.execute(sql).fetchall()
        return [SilenceRuleStore._row_to_rule(r, project_path=project_path) for r in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_rule(
        row: sqlite3.Row,
        project_path: Path | None = None,
    ) -> SilenceRule:
        d = dict(row)
        scene_path = d.get("scene_path", "") or ""
        if project_path and scene_path:
            abs_p = to_absolute(project_path, scene_path)
            if abs_p is not None:
                scene_path = str(abs_p)
        return SilenceRule(
            id=d["id"],
            rule_type=d.get("rule_type", "instance"),
            scope=d.get("scope", "scene"),
            scene_path=scene_path,
            finding_id=d.get("finding_id"),
            lens=d.get("lens", ""),
            severity=d.get("severity", ""),
            text_pattern=d.get("text_pattern", ""),
            note=d.get("note", ""),
            suspended=bool(d.get("suspended", 0)),
            created_at=d.get("created_at", ""),
            suspended_at=d.get("suspended_at", "") or "",
        )


__all__ = ["SilenceRuleStore"]
