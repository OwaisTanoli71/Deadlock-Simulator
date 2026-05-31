"""
Simulation Engine
─────────────────
Drives automated scenarios where processes compete for resources in
real time, producing natural deadlock situations for demonstration.
"""

import threading
import time
import random
from typing import Callable, Optional


class SimulationEngine:
    """
    Runs background threads simulating OS processes requesting / releasing
    resources.  Designed to produce deadlocks naturally so the detector
    and recovery engine can be exercised.
    """

    SCENARIOS = {
        "dining_philosophers": {
            "description": "Classic Dining Philosophers — 5 processes, 5 chopstick resources",
            "processes": [
                ("P1", "Philosopher-1", 2), ("P2", "Philosopher-2", 2),
                ("P3", "Philosopher-3", 2), ("P4", "Philosopher-4", 2),
                ("P5", "Philosopher-5", 2),
            ],
            "resources": [
                ("R1", "Chopstick-1", 1, "mutex"), ("R2", "Chopstick-2", 1, "mutex"),
                ("R3", "Chopstick-3", 1, "mutex"), ("R4", "Chopstick-4", 1, "mutex"),
                ("R5", "Chopstick-5", 1, "mutex"),
            ],
            # Each philosopher needs left then right chopstick
            "allocation_sequence": [
                ("P1","R1"), ("P2","R2"), ("P3","R3"), ("P4","R4"), ("P5","R5"),
                ("P1","R2"), ("P2","R3"), ("P3","R4"), ("P4","R5"), ("P5","R1"),
            ],
        },
        "bankers_classic": {
            "description": "Banker's Algorithm Classic — 4 processes, 3 resource types",
            "processes": [
                ("P0","Process-A",3), ("P1","Process-B",2),
                ("P2","Process-C",4), ("P3","Process-D",1),
            ],
            "resources": [
                ("R0","Tape-Drive",10,"device"),
                ("R1","Disk-Drive",5,"device"),
                ("R2","Printer",7,"device"),
            ],
            "allocation_sequence": [
                ("P0","R0"),("P0","R1"),("P0","R2"),
                ("P1","R0"),("P1","R1"),
                ("P2","R0"),("P2","R2"),
                ("P3","R0"),("P3","R1"),("P3","R2"),
            ],
        },
        "producer_consumer": {
            "description": "Producer-Consumer with shared buffer mutex deadlock",
            "processes": [
                ("P1","Producer-1",3),("P2","Producer-2",3),
                ("P3","Consumer-1",2),("P4","Consumer-2",2),
            ],
            "resources": [
                ("R1","Buffer-Mutex",1,"mutex"),
                ("R2","Full-Semaphore",5,"semaphore"),
                ("R3","Empty-Semaphore",5,"semaphore"),
                ("R4","Printer-Lock",1,"mutex"),
            ],
            "allocation_sequence": [
                ("P1","R1"),("P3","R2"),("P2","R1"),("P4","R2"),
                ("P1","R4"),("P3","R4"),
            ],
        },
        "readers_writers": {
            "description": "Readers-Writers with write starvation deadlock",
            "processes": [
                ("P1","Writer-1",4),("P2","Reader-1",2),
                ("P3","Reader-2",2),("P4","Writer-2",4),("P5","Reader-3",1),
            ],
            "resources": [
                ("R1","DB-Write-Lock",1,"mutex"),
                ("R2","DB-Read-Lock",3,"semaphore"),
                ("R3","Log-File",1,"file"),
            ],
            "allocation_sequence": [
                ("P1","R1"),("P2","R2"),("P3","R2"),
                ("P4","R1"),("P1","R3"),("P4","R3"),
                ("P5","R2"),("P5","R1"),
            ],
        },
        "random_chaos": {
            "description": "Random process/resource generation — unpredictable deadlock",
            "processes": [],  # generated at runtime
            "resources": [],
            "allocation_sequence": [],
        },
    }

    def __init__(self, manager, on_event: Optional[Callable] = None):
        self.manager = manager
        self.on_event = on_event  # callback(event_type, message)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._step_delay = 0.6   # seconds between steps

    def load_scenario(self, scenario_name: str):
        """Load a preset scenario into the resource manager."""
        self.manager.clear_all()

        if scenario_name == "random_chaos":
            self._generate_random_scenario()
            return

        scenario = self.SCENARIOS.get(scenario_name)
        if not scenario:
            return

        for pid, name, priority in scenario["processes"]:
            self.manager.add_process(pid, name, priority)

        for rid, name, instances, rtype in scenario["resources"]:
            self.manager.add_resource(rid, name, instances, rtype)

        self._emit("scenario", f"Loaded scenario: {scenario['description']}")

    def _generate_random_scenario(self):
        """Generate a random set of processes and resources."""
        n_proc = random.randint(3, 6)
        n_res = random.randint(2, 5)
        rtypes = ["mutex", "semaphore", "file", "device"]

        for i in range(1, n_proc + 1):
            self.manager.add_process(f"P{i}", f"Process-{i}", random.randint(1, 5))

        for i in range(1, n_res + 1):
            instances = random.randint(1, 3)
            self.manager.add_resource(
                f"R{i}", f"Resource-{i}", instances, random.choice(rtypes)
            )

        self._emit("scenario", f"Random scenario: {n_proc} processes, {n_res} resources")

    def run_scenario_steps(self, scenario_name: str):
        """Execute allocation steps from scenario in background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._execute_steps, args=(scenario_name,), daemon=True
        )
        self._thread.start()

    def _execute_steps(self, scenario_name: str):
        if scenario_name == "random_chaos":
            self._run_random_chaos()
            return

        scenario = self.SCENARIOS.get(scenario_name, {})
        steps = scenario.get("allocation_sequence", [])

        for pid, rid in steps:
            if not self._running:
                break
            self._emit("step", f"Requesting: {pid} → {rid}")
            self.manager.request_resource(pid, rid)
            time.sleep(self._step_delay)

        self._running = False
        self._emit("done", "Scenario execution complete")

    def _run_random_chaos(self):
        """Random allocation attempts that naturally produce deadlocks."""
        snap = self.manager.get_snapshot()
        pids = list(snap["processes"].keys())
        rids = list(snap["resources"].keys())

        for _ in range(20):
            if not self._running or not pids or not rids:
                break
            pid = random.choice(pids)
            rid = random.choice(rids)
            self._emit("step", f"Chaos: {pid} → {rid}")
            self.manager.request_resource(pid, rid)
            time.sleep(self._step_delay * random.uniform(0.5, 1.5))

        self._running = False
        self._emit("done", "Chaos scenario complete")

    def stop(self):
        self._running = False

    def set_speed(self, delay: float):
        self._step_delay = max(0.1, delay)

    def _emit(self, event_type: str, message: str):
        if self.on_event:
            try:
                self.on_event(event_type, message)
            except Exception:
                pass
