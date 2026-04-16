#!/usr/bin/env python3
"""Tests for excel_utils.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_excel_utils.py -v
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import excel_utils as eu


class TestColumns:
    """Tests for the canonical column schema."""

    def test_columns_includes_headline_and_location(self):
        """New schema should include headline and location columns."""
        assert "headline" in eu.COLUMNS
        assert "location" in eu.COLUMNS

    def test_columns_includes_enrichment_fields(self):
        """Schema should include enrichment columns."""
        assert "enrichment_notes" in eu.COLUMNS
        assert "enriched_at" in eu.COLUMNS

    def test_columns_has_expected_count(self):
        """Schema should have 22 columns (18 old + headline + location + enrichment_notes + enriched_at)."""
        assert len(eu.COLUMNS) == 22

    def test_row_id_is_first_column(self):
        """row_id should always be the first column."""
        assert eu.COLUMNS[0] == "row_id"

    def test_enrichment_notes_position(self):
        """enrichment_notes should be after location."""
        assert eu.COLUMNS.index("enrichment_notes") == 20

    def test_enriched_at_position(self):
        """enriched_at should be the last column."""
        assert eu.COLUMNS.index("enriched_at") == 21


class TestCreate:
    """Tests for create function."""

    def test_create_new_workbook(self, tmp_path):
        """Creating a workbook should include all columns."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        assert wb_path.exists()

        # Verify headers
        wb = eu.get_openpyxl().load_workbook(wb_path)
        ws = wb["Candidates"]
        headers = [cell.value for cell in ws[1]]

        assert headers == eu.COLUMNS


class TestEnsureSchema:
    """Tests for ensure_schema migration function."""

    def create_old_workbook(self, tmp_path, rows_data):
        """Create workbook with old 18-column schema."""
        old_columns = [
            "row_id",
            "name",
            "company",
            "title",
            "profile_url",
            "est_yoe",
            "highest_degree",
            "school",
            "status",
            "next_action",
            "draft_subject",
            "draft_body",
            "date_sent",
            "attempts",
            "last_contact",
            "reply_type",
            "reply_summary",
            "notes",
        ]

        wb_path = tmp_path / "old.xlsx"
        wb = eu.get_openpyxl().Workbook()
        ws = wb.active
        ws.title = "Candidates"
        ws.append(old_columns)

        for i, row_data in enumerate(rows_data, start=1):
            row = [i] + [row_data.get(col, "") for col in old_columns[1:]]
            ws.append(row)

        wb.save(wb_path)
        return str(wb_path)

    def test_migrate_adds_missing_columns(self, tmp_path):
        """Migration should add headline, location, and enrichment columns."""
        rows = [{"name": "John", "title": "Engineer", "status": "Extracted"}]
        wb_path = self.create_old_workbook(tmp_path, rows)

        migrated = eu.ensure_schema(wb_path)
        assert migrated is True

        # Verify new columns exist
        wb = eu.get_openpyxl().load_workbook(wb_path)
        ws = wb["Candidates"]
        headers = [cell.value for cell in ws[1] if cell.value]

        assert "headline" in headers
        assert "location" in headers
        assert "enrichment_notes" in headers
        assert "enriched_at" in headers
        assert len(headers) == 22

    def test_migrate_preserves_existing_data(self, tmp_path):
        """Migration should not lose existing data."""
        rows = [
            {
                "name": "Jane",
                "title": "Senior Engineer",
                "company": "Google",
                "status": "Drafted",
            },
            {
                "name": "Bob",
                "title": "Manager",
                "company": "Meta",
                "status": "Extracted",
            },
        ]
        wb_path = self.create_old_workbook(tmp_path, rows)

        eu.ensure_schema(wb_path)

        # Verify data is preserved
        read_rows = eu.read(wb_path)
        assert len(read_rows) == 2
        assert read_rows[0]["name"] == "Jane"
        assert read_rows[0]["title"] == "Senior Engineer"
        assert read_rows[0]["company"] == "Google"
        assert read_rows[1]["name"] == "Bob"

    def test_migrate_idempotent(self, tmp_path):
        """Running migration twice should return False second time."""
        rows = [{"name": "Alice", "title": "Engineer"}]
        wb_path = self.create_old_workbook(tmp_path, rows)

        first = eu.ensure_schema(wb_path)
        second = eu.ensure_schema(wb_path)

        assert first is True
        assert second is False

    def test_no_migration_needed_for_new_workbook(self, tmp_path):
        """New workbooks should not need migration."""
        wb_path = tmp_path / "new.xlsx"
        eu.create(wb_path)

        migrated = eu.ensure_schema(wb_path)
        assert migrated is False


class TestRead:
    """Tests for read function with schema compatibility."""

    def test_read_old_workbook_returns_none_for_missing_cols(self, tmp_path):
        """Reading old workbook should return None for headline/location."""
        old_columns = [
            "row_id",
            "name",
            "company",
            "title",
            "profile_url",
            "est_yoe",
            "highest_degree",
            "school",
            "status",
            "next_action",
            "draft_subject",
            "draft_body",
            "date_sent",
            "attempts",
            "last_contact",
            "reply_type",
            "reply_summary",
            "notes",
        ]

        wb_path = tmp_path / "old.xlsx"
        wb = eu.get_openpyxl().Workbook()
        ws = wb.active
        ws.title = "Candidates"
        ws.append(old_columns)
        ws.append(
            [1, "John", "Google", "Engineer", "", "", "", "", "Extracted", "draft"]
            + [""] * 8
        )
        wb.save(wb_path)

        rows = eu.read(wb_path)
        assert len(rows) == 1
        assert rows[0]["name"] == "John"
        assert rows[0]["headline"] is None
        assert rows[0]["location"] is None

    def test_read_new_workbook_returns_all_data(self, tmp_path):
        """Reading new workbook should return all columns."""
        wb_path = tmp_path / "new.xlsx"
        eu.create(wb_path)

        eu.append(
            wb_path,
            {
                "name": "Jane",
                "title": "Engineer",
                "company": "Meta",
                "headline": "PyTorch expert",
                "location": "San Francisco",
            },
        )

        rows = eu.read(wb_path)
        assert len(rows) == 1
        assert rows[0]["name"] == "Jane"
        assert rows[0]["headline"] == "PyTorch expert"
        assert rows[0]["location"] == "San Francisco"

    def test_read_with_filters(self, tmp_path):
        """Reading with filters should work with both schemas."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.append(wb_path, {"name": "John", "status": "Extracted", "company": "Google"})
        eu.append(wb_path, {"name": "Jane", "status": "Drafted", "company": "Meta"})
        eu.append(wb_path, {"name": "Bob", "status": "Extracted", "company": "Apple"})

        extracted = eu.read(wb_path, filters={"status": "Extracted"})
        assert len(extracted) == 2
        assert all(r["status"] == "Extracted" for r in extracted)

    def test_read_auto_migrates_old_workbook(self, tmp_path):
        """Reading should migrate old workbooks to the canonical schema."""
        wb_path = TestEnsureSchema().create_old_workbook(
            tmp_path,
            [{"name": "John", "status": "Extracted"}],
        )

        eu.read(wb_path)

        wb = eu.get_openpyxl().load_workbook(wb_path)
        headers = [cell.value for cell in wb["Candidates"][1] if cell.value]
        assert headers == eu.COLUMNS


class TestAppend:
    """Tests for append function."""

    def test_append_assigns_row_id(self, tmp_path):
        """Append should auto-assign row_id."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        id1 = eu.append(wb_path, {"name": "John", "company": "Google"})
        id2 = eu.append(wb_path, {"name": "Jane", "company": "Meta"})

        assert id1 == 1
        assert id2 == 2

        rows = eu.read(wb_path)
        assert rows[0]["row_id"] == 1
        assert rows[1]["row_id"] == 2

    def test_append_stores_headline_and_location(self, tmp_path):
        """Append should store new columns."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.append(
            wb_path,
            {
                "name": "Alice",
                "headline": "ML Engineer at Scale",
                "location": "New York",
            },
        )

        rows = eu.read(wb_path)
        assert rows[0]["headline"] == "ML Engineer at Scale"
        assert rows[0]["location"] == "New York"

    def test_append_auto_migrates_old_workbook(self, tmp_path):
        """Append should migrate an old workbook before writing new rows."""
        wb_path = TestEnsureSchema().create_old_workbook(
            tmp_path,
            [{"name": "John", "status": "Extracted"}],
        )

        row_id = eu.append(wb_path, {"name": "Jane", "headline": "PyTorch"})

        assert row_id == 2
        rows = eu.read(wb_path)
        assert rows[1]["name"] == "Jane"
        assert rows[1]["headline"] == "PyTorch"


class TestUpdate:
    """Tests for update function."""

    def test_update_existing_row(self, tmp_path):
        """Update should modify existing row."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)
        eu.append(wb_path, {"name": "John", "status": "Extracted"})

        eu.update(wb_path, 1, {"status": "Drafted", "draft_subject": "Hello"})

        rows = eu.read(wb_path)
        assert rows[0]["status"] == "Drafted"
        assert rows[0]["draft_subject"] == "Hello"

    def test_update_new_columns(self, tmp_path):
        """Update should work with new headline/location columns."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)
        eu.append(wb_path, {"name": "Jane"})

        eu.update(wb_path, 1, {"headline": "Updated headline", "location": "Remote"})

        rows = eu.read(wb_path)
        assert rows[0]["headline"] == "Updated headline"
        assert rows[0]["location"] == "Remote"

    def test_update_auto_migrates_old_workbook(self, tmp_path):
        """Update should migrate an old workbook before writing new columns."""
        wb_path = TestEnsureSchema().create_old_workbook(
            tmp_path,
            [{"name": "Jane", "status": "Drafted"}],
        )

        eu.update(wb_path, 1, {"headline": "Updated headline", "location": "Remote"})

        rows = eu.read(wb_path)
        assert rows[0]["headline"] == "Updated headline"
        assert rows[0]["location"] == "Remote"


class TestCount:
    """Tests for count function."""

    def test_count_all_rows(self, tmp_path):
        """Count should return total rows without filters."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.append(wb_path, {"name": "John", "status": "Extracted"})
        eu.append(wb_path, {"name": "Jane", "status": "Drafted"})

        assert eu.count(wb_path) == 2

    def test_count_with_filters(self, tmp_path):
        """Count with filters should return matching rows."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.append(wb_path, {"name": "John", "status": "Extracted"})
        eu.append(wb_path, {"name": "Jane", "status": "Drafted"})
        eu.append(wb_path, {"name": "Bob", "status": "Extracted"})

        assert eu.count(wb_path, filters={"status": "Extracted"}) == 2


class TestGetColumnIndex:
    """Tests for get_column_index helper."""

    def test_returns_index_for_valid_column(self):
        """Should return 0-based index for valid columns."""
        assert eu.get_column_index("row_id") == 0
        assert eu.get_column_index("name") == 1
        assert eu.get_column_index("headline") == 18
        assert eu.get_column_index("location") == 19

    def test_returns_none_for_invalid_column(self):
        """Should return None for columns not in schema."""
        assert eu.get_column_index("nonexistent") is None
        assert eu.get_column_index("") is None


class TestUpsert:
    """Tests for upsert function (dedupe/insert-or-update)."""

    def test_upsert_inserts_new_row(self, tmp_path):
        """Upsert should insert new row when key doesn't exist."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        result = eu.upsert(
            wb_path,
            {
                "name": "John Doe",
                "profile_url": "https://linkedin.com/in/johndoe",
                "company": "Google",
                "status": "Extracted",
            },
            key_column="profile_url",
        )

        assert result["action"] == "inserted"
        assert result["row_id"] == 1

        # Verify row was written
        rows = eu.read(wb_path)
        assert len(rows) == 1
        assert rows[0]["name"] == "John Doe"
        assert rows[0]["profile_url"] == "https://linkedin.com/in/johndoe"

    def test_upsert_updates_existing_row(self, tmp_path):
        """Upsert should update existing row when key exists."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        # Insert initial row
        eu.upsert(
            wb_path,
            {
                "name": "John Doe",
                "profile_url": "https://linkedin.com/in/johndoe",
                "company": "Google",
                "status": "Extracted",
            },
            key_column="profile_url",
        )

        # Upsert with same key - should update
        result = eu.upsert(
            wb_path,
            {
                "name": "John Doe Updated",
                "profile_url": "https://linkedin.com/in/johndoe",
                "company": "Meta",
                "status": "Drafted",
            },
            key_column="profile_url",
        )

        assert result["action"] == "updated"
        assert result["row_id"] == 1

        # Verify row was updated
        rows = eu.read(wb_path)
        assert len(rows) == 1
        assert rows[0]["name"] == "John Doe Updated"
        assert rows[0]["company"] == "Meta"
        assert rows[0]["status"] == "Drafted"

    def test_upsert_different_keys_insert_multiple(self, tmp_path):
        """Upsert should insert multiple rows with different keys."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.upsert(
            wb_path,
            {"name": "John", "profile_url": "https://linkedin.com/in/john"},
            key_column="profile_url",
        )
        eu.upsert(
            wb_path,
            {"name": "Jane", "profile_url": "https://linkedin.com/in/jane"},
            key_column="profile_url",
        )

        rows = eu.read(wb_path)
        assert len(rows) == 2
        assert rows[0]["name"] == "John"
        assert rows[1]["name"] == "Jane"

    def test_upsert_empty_key_inserts_new(self, tmp_path):
        """Upsert with empty key should always insert new row."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.upsert(
            wb_path,
            {"name": "John", "profile_url": ""},
            key_column="profile_url",
        )
        eu.upsert(
            wb_path,
            {"name": "Jane", "profile_url": ""},
            key_column="profile_url",
        )

        rows = eu.read(wb_path)
        assert len(rows) == 2

    def test_upsert_auto_migrates_old_workbook(self, tmp_path):
        """Upsert should migrate old workbook before operation."""
        wb_path = TestEnsureSchema().create_old_workbook(
            tmp_path,
            [{"name": "Existing", "profile_url": "https://linkedin.com/in/existing"}],
        )

        result = eu.upsert(
            wb_path,
            {
                "name": "New",
                "profile_url": "https://linkedin.com/in/new",
                "headline": "New headline",  # New column
            },
            key_column="profile_url",
        )

        assert result["action"] == "inserted"

        rows = eu.read(wb_path)
        assert len(rows) == 2
        assert rows[1]["headline"] == "New headline"


class TestGetExistingKeys:
    """Tests for get_existing_keys function (deduplication helper)."""

    def test_get_existing_keys_returns_set(self, tmp_path):
        """Should return set of key values."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.append(
            wb_path,
            {"name": "John", "profile_url": "https://linkedin.com/in/john"},
        )
        eu.append(
            wb_path,
            {"name": "Jane", "profile_url": "https://linkedin.com/in/jane"},
        )

        keys = eu.get_existing_keys(wb_path, key_column="profile_url")

        assert isinstance(keys, set)
        assert len(keys) == 2
        assert "https://linkedin.com/in/john" in keys
        assert "https://linkedin.com/in/jane" in keys

    def test_get_existing_keys_excludes_empty(self, tmp_path):
        """Should exclude empty/None values from set."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.append(
            wb_path,
            {"name": "John", "profile_url": "https://linkedin.com/in/john"},
        )
        eu.append(
            wb_path,
            {"name": "Jane", "profile_url": ""},
        )
        eu.append(wb_path, {"name": "Bob", "profile_url": None})

        keys = eu.get_existing_keys(wb_path, key_column="profile_url")

        assert len(keys) == 1
        assert "https://linkedin.com/in/john" in keys

    def test_get_existing_keys_custom_column(self, tmp_path):
        """Should work with custom key columns."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        eu.append(wb_path, {"name": "John", "company": "Google"})
        eu.append(wb_path, {"name": "Jane", "company": "Meta"})

        keys = eu.get_existing_keys(wb_path, key_column="company")

        assert len(keys) == 2
        assert "Google" in keys
        assert "Meta" in keys

    def test_get_existing_keys_empty_workbook(self, tmp_path):
        """Should return empty set for empty workbook."""
        wb_path = tmp_path / "test.xlsx"
        eu.create(wb_path)

        keys = eu.get_existing_keys(wb_path, key_column="profile_url")

        assert keys == set()


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
