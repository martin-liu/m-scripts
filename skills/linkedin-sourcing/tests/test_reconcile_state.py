#!/usr/bin/env python3
"""Tests for reconcile_state.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import reconcile_state as rs


def test_infer_reconciled_state_uses_workbook_truth():
    """Workbook next_action should determine the reconciled checkpoint."""
    existing_state = {
        "workflow_mode": "reachout",
        "current_phase": "enrich",
        "status": "action_required",
        "action_required": {"code": "browser_manual_intervention"},
    }
    workbook_summary = {
        "total_rows": 5,
        "by_next_action": {"draft": 3, "done": 2},
    }

    result = rs.infer_reconciled_state("12345", existing_state, workbook_summary)

    assert result["project_id"] == "12345"
    assert result["current_phase"] == "draft"
    assert result["status"] == "completed"
    assert result["action_required"] is None
    assert result["last_error"] is None


def test_infer_reconciled_state_empty_workbook_falls_back_to_bootstrap():
    """Empty workbook with no safe progress should resume at create_search."""
    result = rs.infer_reconciled_state(
        "12345",
        {"workflow_mode": "reachout", "current_phase": "create_search"},
        {"total_rows": 0, "by_next_action": {}},
    )

    assert result["current_phase"] == "bootstrap"
    assert "create_search" in result["last_result_summary"]


def test_reconcile_project_dry_run_does_not_write_state(tmp_path, monkeypatch):
    """Dry-run should preview changes without modifying project_state.json."""
    project_dir = tmp_path / "projects" / "12345_role"
    project_dir.mkdir(parents=True)
    config_path = project_dir / "config.sh"
    config_path.write_text(
        'PROJECT_ID="12345"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/999/discover/recruiterSearch"\n',
        encoding="utf-8",
    )
    (project_dir / "workbook.xlsx").write_text("placeholder", encoding="utf-8")
    state_path = project_dir / "project_state.json"
    original_state = {
        "version": 2,
        "project_id": "12345",
        "workflow_mode": "reachout",
        "current_phase": "enrich",
        "status": "action_required",
        "action_required": {"code": "search_not_configured"},
        "updated_at": "2026-01-01T00:00:00",
        "last_result_summary": None,
        "last_error": "blocked",
    }
    state_path.write_text(json.dumps(original_state), encoding="utf-8")

    monkeypatch.setattr(
        rs,
        "get_workbook_summary",
        lambda _path: {"total_rows": 4, "by_next_action": {"draft": 4}},
    )

    result = rs.reconcile_project(str(config_path), apply=False, work_dir=tmp_path)

    assert result["success"] is True
    assert result["changed"] is True
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved_state["status"] == "action_required"
    assert saved_state["action_required"] == {"code": "search_not_configured"}


def test_reconcile_project_apply_writes_state_and_clears_extraction_state(
    tmp_path,
    monkeypatch,
):
    """Apply should save reconciled state and clear stale extraction resume state."""
    project_dir = tmp_path / "projects" / "12345_role"
    project_dir.mkdir(parents=True)
    config_path = project_dir / "config.sh"
    config_path.write_text(
        'PROJECT_ID="12345"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/999/discover/recruiterSearch"\n',
        encoding="utf-8",
    )
    (project_dir / "workbook.xlsx").write_text("placeholder", encoding="utf-8")
    state_path = project_dir / "project_state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 2,
                "project_id": "12345",
                "workflow_mode": "reachout",
                "current_phase": "extract",
                "status": "running",
                "action_required": None,
                "updated_at": "2026-01-01T00:00:00",
                "last_result_summary": None,
                "last_error": "stale",
            }
        ),
        encoding="utf-8",
    )
    extraction_state_path = tmp_path / "runtime" / "extraction-state" / "state.json"
    extraction_state_path.parent.mkdir(parents=True)
    extraction_state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "project_id": "12345",
                "workbook_path": str(project_dir / "workbook.xlsx"),
                "config_path": str(config_path),
                "status": "completed",
                "updated_at": "2026-01-01T00:00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        rs,
        "get_workbook_summary",
        lambda _path: {"total_rows": 3, "by_next_action": {"review": 3}},
    )
    monkeypatch.setattr(
        rs,
        "get_extraction_state_path",
        lambda *_args, **_kwargs: {
            "success": True,
            "path": extraction_state_path,
            "error": None,
        },
    )

    result = rs.reconcile_project(str(config_path), apply=True, work_dir=tmp_path)

    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["changed"] is True
    assert result["cleared_extraction_state"] is True
    assert saved_state["current_phase"] == "review"
    assert saved_state["status"] == "completed"
    assert saved_state["action_required"] is None
    assert extraction_state_path.exists() is False


def test_reconcile_project_refuses_active_extraction_recovery(tmp_path, monkeypatch):
    """Reconcile should fail closed when interrupted extraction recovery exists."""
    project_dir = tmp_path / "projects" / "12345_role"
    project_dir.mkdir(parents=True)
    config_path = project_dir / "config.sh"
    config_path.write_text(
        'PROJECT_ID="12345"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/999/discover/recruiterSearch"\n',
        encoding="utf-8",
    )
    (project_dir / "workbook.xlsx").write_text("placeholder", encoding="utf-8")
    extraction_state_path = tmp_path / "runtime" / "extraction-state" / "state.json"
    extraction_state_path.parent.mkdir(parents=True)
    extraction_state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "project_id": "12345",
                "workbook_path": str(project_dir / "workbook.xlsx"),
                "config_path": str(config_path),
                "status": "running",
                "updated_at": "2026-01-01T00:00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        rs,
        "get_workbook_summary",
        lambda _path: {"total_rows": 2, "by_next_action": {"filter": 2}},
    )
    monkeypatch.setattr(
        rs,
        "get_extraction_state_path",
        lambda *_args, **_kwargs: {
            "success": True,
            "path": extraction_state_path,
            "error": None,
        },
    )

    result = rs.reconcile_project(str(config_path), apply=True, work_dir=tmp_path)

    assert result["success"] is False
    assert "Do not reconcile yet" in result["error"]
    assert extraction_state_path.exists() is True


def test_reconcile_project_refuses_unreadable_extraction_state(tmp_path, monkeypatch):
    """Unreadable extraction resume state should fail closed."""
    project_dir = tmp_path / "projects" / "12345_role"
    project_dir.mkdir(parents=True)
    config_path = project_dir / "config.sh"
    config_path.write_text('PROJECT_ID="12345"\n', encoding="utf-8")
    (project_dir / "workbook.xlsx").write_text("placeholder", encoding="utf-8")
    extraction_state_path = tmp_path / "runtime" / "extraction-state" / "state.json"
    extraction_state_path.parent.mkdir(parents=True)
    extraction_state_path.write_text("not json", encoding="utf-8")

    monkeypatch.setattr(
        rs,
        "get_workbook_summary",
        lambda _path: {"total_rows": 2, "by_next_action": {"filter": 2}},
    )
    monkeypatch.setattr(
        rs,
        "get_extraction_state_path",
        lambda *_args, **_kwargs: {
            "success": True,
            "path": extraction_state_path,
            "error": None,
        },
    )

    result = rs.reconcile_project(str(config_path), apply=True, work_dir=tmp_path)

    assert result["success"] is False
    assert "unreadable" in result["error"]
    assert extraction_state_path.exists() is True


def test_reconcile_project_refuses_when_extraction_state_lookup_fails(
    tmp_path,
    monkeypatch,
):
    """Extraction-state lookup failure should stop reconcile."""
    project_dir = tmp_path / "projects" / "12345_role"
    project_dir.mkdir(parents=True)
    config_path = project_dir / "config.sh"
    config_path.write_text('PROJECT_ID="12345"\n', encoding="utf-8")
    (project_dir / "workbook.xlsx").write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        rs,
        "get_workbook_summary",
        lambda _path: {"total_rows": 2, "by_next_action": {"filter": 2}},
    )
    monkeypatch.setattr(
        rs,
        "get_extraction_state_path",
        lambda *_args, **_kwargs: {
            "success": False,
            "path": None,
            "error": "lookup failed",
        },
    )

    result = rs.reconcile_project(str(config_path), apply=True, work_dir=tmp_path)

    assert result["success"] is False
    assert result["error"] == "lookup failed"
