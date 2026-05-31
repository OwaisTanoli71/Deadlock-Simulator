"""
Recovery Engine
───────────────
Implements four automatic deadlock recovery strategies drawn from
real OS literature (Silberschatz, Tanenbaum):

1. Process Termination  — kill lowest-priority victim
2. Resource Preemption  — steal a resource from a victim
3. Process Rollback     — reset victim to safe checkpoint, release resources
4. Kill All             — terminate every deadlocked process (nuclear option)

Each strategy returns a RecoveryAction that the GUI can display.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time


@dataclass
class RecoveryAction:
    """Describes what the recovery engine did and its rationale."""
    strategy: str
    affected_processes: List[str]
    affected_resources: List[str]
    steps: List[str]                    # ordered log of actions taken
    success: bool
    timestamp: str
    cost_estimate: str                  # rough "OS cost" commentary

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "affected_processes": self.affected_processes,
            "affected_resources": self.affected_resources,
            "steps": self.steps,
            "success": self.success,
            "timestamp": self.timestamp,
            "cost_estimate": self.cost_estimate,
        }


class RecoveryEngine:
    """
    Automatic recovery strategies.  All methods accept a live ResourceManager
    and a DeadlockResult, mutate the manager to resolve the deadlock, and
    return a RecoveryAction describing what happened.
    """

    def recover(self, manager, detection_result, strategy: str) -> RecoveryAction:
        """
        Dispatch to the requested recovery strategy.

        Parameters
        ----------
        manager          : ResourceManager (live, will be mutated)
        detection_result : DeadlockResult
        strategy         : 'terminate' | 'preempt' | 'rollback' | 'kill_all'
        """
        ts = time.strftime("%H:%M:%S")

        if not detection_result.detected:
            return RecoveryAction(
                strategy=strategy,
                affected_processes=[],
                affected_resources=[],
                steps=["No deadlock detected — no recovery needed."],
                success=False,
                timestamp=ts,
                cost_estimate="N/A",
            )

        deadlocked = detection_result.deadlocked_processes
        if not deadlocked:
            return RecoveryAction(
                strategy=strategy,
                affected_processes=[],
                affected_resources=[],
                steps=["Deadlock detected but no process list available."],
                success=False,
                timestamp=ts,
                cost_estimate="N/A",
            )

        if strategy == "preempt":
            return self._preempt(manager, deadlocked, detection_result.deadlocked_resources, ts)
        elif strategy == "rollback":
            return self._rollback(manager, deadlocked, ts)
        elif strategy == "kill_all":
            return self._kill_all(manager, deadlocked, ts)
        else:
            return self._terminate_victim(manager, deadlocked, ts)

    # ── Strategy 1: Terminate lowest-priority victim ──────────────────────────

    def _terminate_victim(self, manager, deadlocked: List[str], ts: str) -> RecoveryAction:
        """
        Select the lowest-priority deadlocked process and terminate it.
        Classic OS approach — minimal disruption if victim has done little work.
        """
        steps = ["[STRATEGY] Process Termination — kill lowest-priority victim"]

        snap = manager.get_snapshot()
        processes = snap["processes"]

        # Pick victim: lowest priority, then shortest name as tie-break
        victim_pid = min(
            deadlocked,
            key=lambda pid: (
                processes.get(pid, {}).get("priority", 99),
                processes.get(pid, {}).get("name", ""),
            ),
        )

        victim = processes.get(victim_pid, {})
        steps.append(f"Selected victim: {victim.get('name', victim_pid)} (priority={victim.get('priority', '?')})")
        steps.append(f"Releasing all resources held by {victim.get('name', victim_pid)}…")

        released = list(victim.get("allocated", {}).keys())
        for rid in released:
            rname = snap["resources"].get(rid, {}).get("name", rid)
            steps.append(f"  ↳ Released resource [{rname}]")

        success = manager.terminate_process(victim_pid, reason="deadlock_recovery")
        steps.append(f"Process {victim.get('name', victim_pid)} terminated {'successfully' if success else '(error)'}.")
        steps.append("Other processes can now continue.")

        return RecoveryAction(
            strategy="Process Termination",
            affected_processes=[victim_pid],
            affected_resources=released,
            steps=steps,
            success=success,
            timestamp=ts,
            cost_estimate="Medium — work done by victim is lost; remaining processes unaffected.",
        )

    # ── Strategy 2: Resource Preemption ──────────────────────────────────────

    def _preempt(self, manager, deadlocked: List[str],
                 deadlocked_rids: List[str], ts: str) -> RecoveryAction:
        """
        Preempt one resource from one deadlocked process and give it to a waiter.
        The victim process is rolled back (not killed).
        This mirrors how OS handles mutex preemption in real-time systems.
        """
        steps = ["[STRATEGY] Resource Preemption — steal resource from waiting victim"]

        snap = manager.get_snapshot()
        processes = snap["processes"]
        resources = snap["resources"]

        # Find a deadlocked process that holds something another deadlocked process wants
        victim_pid = None
        stolen_rid = None
        beneficiary_pid = None

        for pid in deadlocked:
            p = processes.get(pid, {})
            held = set(p.get("allocated", {}).keys())
            for other_pid in deadlocked:
                if other_pid == pid:
                    continue
                wanted = set(processes.get(other_pid, {}).get("requested", {}).keys())
                overlap = held & wanted
                if overlap:
                    victim_pid = pid
                    stolen_rid = next(iter(overlap))
                    beneficiary_pid = other_pid
                    break
            if victim_pid:
                break

        if not victim_pid:
            # Fallback: rollback first process
            steps.append("No direct preemption candidate found — falling back to rollback.")
            return self._rollback(manager, deadlocked[:1], ts)

        victim_name = processes.get(victim_pid, {}).get("name", victim_pid)
        bene_name = processes.get(beneficiary_pid, {}).get("name", beneficiary_pid)
        rid_name = resources.get(stolen_rid, {}).get("name", stolen_rid)

        steps.append(f"Victim selected: {victim_name} (will be rolled back)")
        steps.append(f"Preempting resource [{rid_name}] from {victim_name}")

        # Release stolen resource from victim
        success = manager.release_resource(victim_pid, stolen_rid)
        steps.append(f"  ↳ Resource [{rid_name}] returned to pool")

        # Immediately grant to beneficiary
        granted = manager.request_resource(beneficiary_pid, stolen_rid)
        steps.append(f"  ↳ Granted [{rid_name}] to {bene_name}: {'✓' if granted else '✗'}")

        # Victim process marked blocked (would normally be re-queued)
        with manager._lock:
            if victim_pid in manager.processes:
                manager.processes[victim_pid].state = "rolled_back"
        steps.append(f"{victim_name} set to rolled_back — will re-request resources later.")
        manager._log("preempt", f"Preempted [{rid_name}] from {victim_name} → {bene_name}")

        return RecoveryAction(
            strategy="Resource Preemption",
            affected_processes=[victim_pid, beneficiary_pid],
            affected_resources=[stolen_rid],
            steps=steps,
            success=success,
            timestamp=ts,
            cost_estimate="Low-Medium — victim loses the preempted resource temporarily; minimal rollback.",
        )

    # ── Strategy 3: Rollback ─────────────────────────────────────────────────

    def _rollback(self, manager, deadlocked: List[str], ts: str) -> RecoveryAction:
        """
        Roll back ONE deadlocked process (lowest priority) to a safe state.
        All its resources are released; it can re-request later.
        Preferred when checkpointing is available (databases, transactional systems).
        """
        steps = ["[STRATEGY] Process Rollback — reset victim to safe checkpoint"]

        snap = manager.get_snapshot()
        processes = snap["processes"]

        victim_pid = min(
            deadlocked,
            key=lambda pid: processes.get(pid, {}).get("priority", 99),
        )
        victim = processes.get(victim_pid, {})
        victim_name = victim.get("name", victim_pid)
        released = list(victim.get("allocated", {}).keys())

        steps.append(f"Rolling back: {victim_name} (priority={victim.get('priority','?')})")
        for rid in released:
            rname = snap["resources"].get(rid, {}).get("name", rid)
            steps.append(f"  ↳ Releasing [{rname}] back to pool")

        success = manager.rollback_process(victim_pid)
        steps.append(f"{victim_name} rolled back {'successfully' if success else '(error)'}.")
        steps.append("Process state preserved — it may re-request resources in future cycles.")

        return RecoveryAction(
            strategy="Process Rollback",
            affected_processes=[victim_pid],
            affected_resources=released,
            steps=steps,
            success=success,
            timestamp=ts,
            cost_estimate="Low — process survives, work may be partially repeated. Best with checkpointing.",
        )

    # ── Strategy 4: Kill All ──────────────────────────────────────────────────

    def _kill_all(self, manager, deadlocked: List[str], ts: str) -> RecoveryAction:
        """
        Terminate ALL deadlocked processes simultaneously.
        Guaranteed to break any deadlock but maximum disruption.
        Used as last resort in batch processing systems.
        """
        steps = ["[STRATEGY] Kill All — terminate every deadlocked process (nuclear option)"]

        snap = manager.get_snapshot()
        processes = snap["processes"]

        all_released = []
        terminated = []

        for pid in deadlocked:
            pname = processes.get(pid, {}).get("name", pid)
            released = list(processes.get(pid, {}).get("allocated", {}).keys())
            all_released.extend(released)
            ok = manager.terminate_process(pid, reason="kill_all_recovery")
            if ok:
                terminated.append(pid)
                rnames = [snap["resources"].get(r, {}).get("name", r) for r in released]
                steps.append(f"  ✗ Terminated {pname} — freed: {', '.join(rnames) or 'none'}")

        steps.append(f"Total terminated: {len(terminated)} process(es).")
        steps.append("All deadlocked resources returned to pool.")
        steps.append("⚠ Significant work loss — use only when system stability is critical.")

        return RecoveryAction(
            strategy="Kill All Deadlocked",
            affected_processes=terminated,
            affected_resources=list(set(all_released)),
            steps=steps,
            success=len(terminated) > 0,
            timestamp=ts,
            cost_estimate="High — all deadlocked processes lose work. System recovers immediately.",
        )
