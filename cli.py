"""
CLI Mode — Headless deadlock simulation and testing (no Tkinter required).
Usage:  python cli.py [scenario]
        python cli.py dining_philosophers
        python cli.py bankers_classic
        python cli.py random_chaos
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.resource_manager import ResourceManager
from core.deadlock_detector import DeadlockDetector
from core.recovery_engine import RecoveryEngine
from core.simulation_engine import SimulationEngine


RESET  = "\033[0m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"


def banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════════╗
║   DEADLOCK DETECTION & RECOVERY SIMULATOR  (CLI MODE)   ║
║   OS-Level Resource Management Engine — Python          ║
╚══════════════════════════════════════════════════════════╝{RESET}
""")


def print_state(manager):
    snap = manager.get_snapshot()
    print(f"\n{BOLD}{'─'*60}")
    print(f"  RESOURCES")
    print(f"{'─'*60}{RESET}")
    for rid, r in snap["resources"].items():
        bar = "█" * r["allocated"] + "░" * r["available"]
        print(f"  {CYAN}{rid}{RESET} {r['name']:<20} [{bar}] {r['available']}/{r['total']} free  ({r['type']})")

    print(f"\n{BOLD}{'─'*60}")
    print(f"  PROCESSES")
    print(f"{'─'*60}{RESET}")
    state_color = {"running": GREEN, "waiting": YELLOW, "blocked": RED,
                   "terminated": DIM, "rolled_back": "\033[35m"}
    for pid, p in snap["processes"].items():
        sc = state_color.get(p["state"], RESET)
        alloc = ", ".join(f"{r}:{c}" for r, c in p["allocated"].items()) or "none"
        req   = ", ".join(f"{r}:{c}" for r, c in p["requested"].items()) or "none"
        print(f"  {CYAN}{pid}{RESET} {p['name']:<20} {sc}[{p['state']:^12}]{RESET}  "
              f"holds=[{alloc}]  wants=[{req}]  pri={p['priority']}")


def print_detection(result):
    print(f"\n{BOLD}{'═'*60}")
    print(f"  DETECTION: {result.algorithm}")
    print(f"{'═'*60}{RESET}")
    if result.detected:
        print(f"  {RED}{BOLD}⚠  DEADLOCK DETECTED!{RESET}")
        print(f"  Deadlocked: {', '.join(result.deadlocked_processes)}")
        print(f"  Resources:  {', '.join(result.deadlocked_resources) or 'n/a'}")
        for cycle in result.cycle_path:
            print(f"  {RED}↻ Cycle: {cycle}{RESET}")
    else:
        print(f"  {GREEN}{BOLD}✓  No deadlock — system safe{RESET}")
        if result.safe_sequence:
            print(f"  Safe sequence: {' → '.join(result.safe_sequence)}")
    print(f"  {DIM}{result.details}{RESET}")


def print_recovery(action):
    print(f"\n{BOLD}{'═'*60}")
    print(f"  RECOVERY: {action.strategy}")
    print(f"{'═'*60}{RESET}")
    for step in action.steps:
        color = GREEN if ("success" in step.lower() or "✓" in step) \
                else RED if ("✗" in step or "error" in step.lower()) \
                else CYAN
        print(f"  {color}{step}{RESET}")
    print(f"  {YELLOW}💰 Cost: {action.cost_estimate}{RESET}")


def run_demo(scenario_name: str = "dining_philosophers"):
    banner()
    manager  = ResourceManager()
    detector = DeadlockDetector()
    recovery = RecoveryEngine()
    sim      = SimulationEngine(manager)

    print(f"{CYAN}Loading scenario: {scenario_name}{RESET}")
    sim.load_scenario(scenario_name)

    # Execute all allocation steps synchronously
    if scenario_name != "random_chaos":
        scenario = sim.SCENARIOS.get(scenario_name, {})
        steps    = scenario.get("allocation_sequence", [])
        print(f"\nExecuting {len(steps)} allocation steps...")
        for pid, rid in steps:
            ok = manager.request_resource(pid, rid)
            status = f"{GREEN}allocated{RESET}" if ok else f"{YELLOW}waiting{RESET}"
            print(f"  {pid} → {rid}: {status}")
    else:
        import random
        snap = manager.get_snapshot()
        pids = list(snap["processes"].keys())
        rids = list(snap["resources"].keys())
        for _ in range(15):
            if pids and rids:
                manager.request_resource(random.choice(pids), random.choice(rids))

    print_state(manager)

    # Run all three detection algorithms
    snap = manager.get_snapshot()
    for algo in ["rag", "bankers", "wfg"]:
        result = detector.detect(snap, algo)
        print_detection(result)

    # Run all four recovery strategies
    snap   = manager.get_snapshot()
    result = detector.detect(snap, "rag")

    if result.detected:
        print(f"\n{YELLOW}Running recovery strategies...{RESET}")

        # Demonstrate one strategy
        action = recovery.recover(manager, result, "terminate")
        print_recovery(action)

        print_state(manager)

        # Re-detect after recovery
        snap2   = manager.get_snapshot()
        result2 = detector.detect(snap2, "rag")
        print_detection(result2)

    print(f"\n{GREEN}{BOLD}Demo complete.{RESET}\n")


if __name__ == "__main__":
    scenario = sys.argv[1] if len(sys.argv) > 1 else "dining_philosophers"
    valid = list(SimulationEngine.SCENARIOS.keys())
    if scenario not in valid:
        print(f"Unknown scenario '{scenario}'. Valid: {', '.join(valid)}")
        sys.exit(1)
    run_demo(scenario)
