"""Tests for snapshot system and rollback engine."""

import unittest
import os
import tempfile
import shutil
from app.core.snapshot import Snapshot, SnapshotManager, SnapshotEntry


class TestSnapshot(unittest.TestCase):

    def test_snapshot_creation(self):
        snap = Snapshot(
            snapshot_id="test_snapshot",
            timestamp="2026-01-01T00:00:00",
            description="Test",
        )
        entry = SnapshotEntry(
            category="power",
            key="active_plan",
            description="Power Plan",
            current_value="balanced",
            backup_value="balanced",
        )
        snap.add_entry(entry)
        self.assertEqual(len(snap.entries), 1)
        self.assertEqual(snap.entries[0].category, "power")

    def test_snapshot_to_dict(self):
        snap = Snapshot(
            snapshot_id="test",
            timestamp="2026-01-01T00:00:00",
            description="Test",
        )
        snap.add_entry(SnapshotEntry(category="test", key="key1", description="Test Entry"))
        d = snap.to_dict()
        self.assertEqual(d["snapshot_id"], "test")
        self.assertEqual(len(d["entries"]), 1)


class TestSnapshotManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.manager = SnapshotManager(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_list_empty(self):
        snapshots = self.manager.list_snapshots()
        self.assertEqual(len(snapshots), 0)

    def test_snapshot_persistence(self):
        snap = Snapshot(
            snapshot_id="test_2026-01-01",
            timestamp="2026-01-01T00:00:00",
            description="Test snapshot",
        )
        snap.add_entry(SnapshotEntry(category="power", key="plan", description="Plan"))
        self.manager._save(snap)

        loaded = self.manager.load_snapshot("test_2026-01-01")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.snapshot_id, "test_2026-01-01")
        self.assertEqual(len(loaded.entries), 1)

    def test_list_snapshots(self):
        # Create two snapshots
        for i in range(2):
            snap = Snapshot(
                snapshot_id=f"snap_{i}",
                timestamp=f"2026-01-0{i+1}T00:00:00",
                description=f"Snapshot {i}",
            )
            self.manager._save(snap)

        snapshots = self.manager.list_snapshots()
        self.assertEqual(len(snapshots), 2)

    def test_delete_snapshot(self):
        snap = Snapshot(snapshot_id="to_delete", timestamp="2026-01-01T00:00:00")
        self.manager._save(snap)
        self.assertTrue(self.manager.delete_snapshot("to_delete"))
        self.assertIsNone(self.manager.load_snapshot("to_delete"))


if __name__ == "__main__":
    unittest.main()
