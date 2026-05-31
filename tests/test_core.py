"""
Unit Tests — Deadlock Detection & Recovery Engine
Run with:  python -m pytest tests/ -v
       or:  python tests/test_core.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from core.resource_manager import ResourceManager
from core.deadlock_detector import DeadlockDetector
from core.recovery_engine import RecoveryEngine


class TestResourceManager(unittest.TestCase):

    def setUp(self):
        self.mgr = ResourceManager()

    def test_add_process(self):
        p = self.mgr.add_process("P1", "Test", 3)
        self.assertEqual(p.pid, "P1")
        self.assertEqual(p.priority, 3)

    def test_add_resource(self):
        r = self.mgr.add_resource("R1", "Mutex", 2, "mutex")
        self.assertEqual(r.total_instances, 2)
        self.assertEqual(r.available_instances, 2)

    def test_successful_allocation(self):
        self.mgr.add_process("P1", "Test", 1)
        self.mgr.add_resource("R1", "Mutex", 1)
        ok = self.mgr.request_resource("P1", "R1")
        self.assertTrue(ok)
        snap = self.mgr.get_snapshot()
        self.assertEqual(snap["resources"]["R1"]["available"], 0)
        self.assertEqual(snap["processes"]["P1"]["state"], "running")

    def test_blocked_when_unavailable(self):
        self.mgr.add_process("P1", "A", 1)
        self.mgr.add_process("P2", "B", 1)
        self.mgr.add_resource("R1", "Mutex", 1)
        self.mgr.request_resource("P1", "R1")
        ok = self.mgr.request_resource("P2", "R1")
        self.assertFalse(ok)
        snap = self.mgr.get_snapshot()
        self.assertEqual(snap["processes"]["P2"]["state"], "waiting")

    def test_release_resource(self):
        self.mgr.add_process("P1", "Test", 1)
        self.mgr.add_resource("R1", "Mutex", 1)
        self.mgr.request_resource("P1", "R1")
        self.mgr.release_resource("P1", "R1")
        snap = self.mgr.get_snapshot()
        self.assertEqual(snap["resources"]["R1"]["available"], 1)

    def test_terminate_releases_resources(self):
        self.mgr.add_process("P1", "Test", 1)
        self.mgr.add_resource("R1", "Mutex", 2)
        self.mgr.request_resource("P1", "R1", 2)
        self.mgr.terminate_process("P1", "test")
        snap = self.mgr.get_snapshot()
        self.assertEqual(snap["resources"]["R1"]["available"], 2)
        self.assertEqual(snap["processes"]["P1"]["state"], "terminated")

    def test_rollback_releases_resources(self):
        self.mgr.add_process("P1", "Test", 1)
        self.mgr.add_resource("R1", "Mutex", 1)
        self.mgr.request_resource("P1", "R1")
        self.mgr.rollback_process("P1")
        snap = self.mgr.get_snapshot()
        self.assertEqual(snap["resources"]["R1"]["available"], 1)
        self.assertEqual(snap["processes"]["P1"]["state"], "rolled_back")


class TestDeadlockDetector(unittest.TestCase):

    def setUp(self):
        self.mgr = ResourceManager()
        self.det = DeadlockDetector()

    def _classic_deadlock(self):
        """P1 holds R1, wants R2. P2 holds R2, wants R1."""
        self.mgr.add_process("P1", "Proc1", 2)
        self.mgr.add_process("P2", "Proc2", 2)
        self.mgr.add_resource("R1", "Mutex1", 1)
        self.mgr.add_resource("R2", "Mutex2", 1)
        self.mgr.request_resource("P1", "R1")
        self.mgr.request_resource("P2", "R2")
        self.mgr.request_resource("P1", "R2")  # blocked
        self.mgr.request_resource("P2", "R1")  # blocked — deadlock!

    def test_rag_detects_deadlock(self):
        self._classic_deadlock()
        snap = self.mgr.get_snapshot()
        result = self.det.detect(snap, "rag")
        self.assertTrue(result.detected)
        self.assertIn("P1", result.deadlocked_processes)
        self.assertIn("P2", result.deadlocked_processes)

    def test_wfg_detects_deadlock(self):
        self._classic_deadlock()
        snap = self.mgr.get_snapshot()
        result = self.det.detect(snap, "wfg")
        self.assertTrue(result.detected)

    def test_bankers_detects_unsafe(self):
        self._classic_deadlock()
        snap = self.mgr.get_snapshot()
        result = self.det.detect(snap, "bankers")
        self.assertTrue(result.detected)

    def test_no_deadlock_clean_state(self):
        self.mgr.add_process("P1", "A", 1)
        self.mgr.add_resource("R1", "Mutex", 2)
        self.mgr.request_resource("P1", "R1")
        snap = self.mgr.get_snapshot()
        result = self.det.detect(snap, "rag")
        self.assertFalse(result.detected)

    def test_empty_state_no_deadlock(self):
        snap = self.mgr.get_snapshot()
        result = self.det.detect(snap, "rag")
        self.assertFalse(result.detected)

    def test_three_process_cycle(self):
        """P1→R1→P2→R2→P3→R3→P1 (ring deadlock)"""
        for i in range(1, 4):
            self.mgr.add_process(f"P{i}", f"Proc{i}", 2)
            self.mgr.add_resource(f"R{i}", f"Mutex{i}", 1)
        self.mgr.request_resource("P1", "R1")
        self.mgr.request_resource("P2", "R2")
        self.mgr.request_resource("P3", "R3")
        self.mgr.request_resource("P1", "R2")
        self.mgr.request_resource("P2", "R3")
        self.mgr.request_resource("P3", "R1")
        snap = self.mgr.get_snapshot()
        result = self.det.detect(snap, "rag")
        self.assertTrue(result.detected)


class TestRecoveryEngine(unittest.TestCase):

    def setUp(self):
        self.mgr = ResourceManager()
        self.det = DeadlockDetector()
        self.rec = RecoveryEngine()

    def _make_deadlock(self):
        self.mgr.add_process("P1", "HighPri", 5)
        self.mgr.add_process("P2", "LowPri", 1)
        self.mgr.add_resource("R1", "Mutex1", 1)
        self.mgr.add_resource("R2", "Mutex2", 1)
        self.mgr.request_resource("P1", "R1")
        self.mgr.request_resource("P2", "R2")
        self.mgr.request_resource("P1", "R2")
        self.mgr.request_resource("P2", "R1")
        snap = self.mgr.get_snapshot()
        return self.det.detect(snap, "rag")

    def test_terminate_resolves_deadlock(self):
        result = self._make_deadlock()
        action = self.rec.recover(self.mgr, result, "terminate")
        self.assertTrue(action.success)
        snap2 = self.mgr.get_snapshot()
        result2 = self.det.detect(snap2, "rag")
        self.assertFalse(result2.detected)

    def test_rollback_resolves_deadlock(self):
        result = self._make_deadlock()
        action = self.rec.recover(self.mgr, result, "rollback")
        self.assertTrue(action.success)
        snap2 = self.mgr.get_snapshot()
        result2 = self.det.detect(snap2, "rag")
        self.assertFalse(result2.detected)

    def test_kill_all_resolves_deadlock(self):
        result = self._make_deadlock()
        action = self.rec.recover(self.mgr, result, "kill_all")
        self.assertTrue(action.success)
        snap2 = self.mgr.get_snapshot()
        result2 = self.det.detect(snap2, "rag")
        self.assertFalse(result2.detected)

    def test_terminate_kills_lowest_priority(self):
        result = self._make_deadlock()
        action = self.rec.recover(self.mgr, result, "terminate")
        # P2 has lower priority (1) so it should be victim
        self.assertIn("P2", action.affected_processes)

    def test_no_deadlock_recovery_fails_gracefully(self):
        result = self._make_deadlock()
        # Manually clear deadlock flag
        result.detected = False
        action = self.rec.recover(self.mgr, result, "terminate")
        self.assertFalse(action.success)


if __name__ == "__main__":
    unittest.main(verbosity=2)
