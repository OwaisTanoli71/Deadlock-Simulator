"""
Deadlock Detection Engine
─────────────────────────
Implements three classic OS detection strategies:

1. Resource Allocation Graph (RAG) cycle detection  — O(V+E)  DFS
2. Banker's Algorithm safety check                  — O(n²·m) 
3. Wait-For Graph (WFG)                             — process-only view of RAG

All algorithms operate on a snapshot, never mutating live state.
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
import time


@dataclass
class DeadlockResult:
    """Result from a deadlock detection run."""
    detected: bool
    algorithm: str
    deadlocked_processes: List[str]
    deadlocked_resources: List[str]
    cycle_path: List[str]           # human-readable cycle description
    safe_sequence: List[str]        # Banker's safe order (empty if unsafe)
    timestamp: str
    details: str

    def to_dict(self) -> dict:
        return {
            "detected": self.detected,
            "algorithm": self.algorithm,
            "deadlocked_processes": self.deadlocked_processes,
            "deadlocked_resources": self.deadlocked_resources,
            "cycle_path": self.cycle_path,
            "safe_sequence": self.safe_sequence,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class DeadlockDetector:
    """
    Stateless detection engine — call detect() with a manager snapshot.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def detect(self, manager_snapshot: dict, algorithm: str = "rag") -> DeadlockResult:
        """
        Run the selected detection algorithm against a resource-manager snapshot.

        Parameters
        ----------
        manager_snapshot : dict   — output of ResourceManager.get_snapshot()
        algorithm        : str    — 'rag' | 'bankers' | 'wfg'
        """
        ts = time.strftime("%H:%M:%S")
        processes = manager_snapshot.get("processes", {})
        resources = manager_snapshot.get("resources", {})

        if algorithm == "bankers":
            return self._bankers_detection(processes, resources, ts)
        elif algorithm == "wfg":
            return self._wfg_detection(processes, resources, ts)
        else:
            return self._rag_detection(processes, resources, ts)

    # ── Resource Allocation Graph  ────────────────────────────────────────────

    def _rag_detection(self, processes: dict, resources: dict, ts: str) -> DeadlockResult:
        """
        Build the RAG and search for cycles using DFS.

        Nodes  : processes (P_i) and resources (R_j)
        Edges  : allocation edge R_j → P_i  (resource held by process)
                 request edge   P_i → R_j  (process waiting for resource)
        A cycle indicates deadlock.
        """
        # Build adjacency list
        adj: Dict[str, List[str]] = {pid: [] for pid in processes}
        adj.update({rid: [] for rid in resources})

        deadlocked_pids = set()
        deadlocked_rids = set()

        for pid, p in processes.items():
            # request edges: P → R
            for rid in p.get("requested", {}):
                if rid in adj:
                    adj[pid].append(rid)
            # allocation edges: R → P
            for rid in p.get("allocated", {}):
                if rid in adj:
                    adj[rid].append(pid)

        # DFS cycle detection
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        parent: Dict[str, Optional[str]] = {}
        cycles: List[List[str]] = []

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    parent[neighbor] = node
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle — reconstruct it
                    cycle = [neighbor]
                    cur = node
                    while cur != neighbor:
                        cycle.append(cur)
                        cur = parent.get(cur, neighbor)
                    cycle.append(neighbor)
                    cycle.reverse()
                    cycles.append(cycle)
                    return True
            rec_stack.discard(node)
            return False

        for node in list(adj.keys()):
            if node not in visited:
                parent[node] = None
                dfs(node)

        detected = bool(cycles)
        cycle_path = []

        if detected:
            for cycle in cycles:
                for node in cycle:
                    if node in processes:
                        deadlocked_pids.add(node)
                    elif node in resources:
                        deadlocked_rids.add(node)
                cycle_labels = []
                for n in cycle:
                    label = processes[n]["name"] if n in processes else f"[{resources[n]['name']}]"
                    cycle_labels.append(label)
                cycle_path.append(" → ".join(cycle_labels))

            details = (
                f"RAG cycle detection found {len(cycles)} cycle(s). "
                f"{len(deadlocked_pids)} process(es) deadlocked on "
                f"{len(deadlocked_rids)} resource(s)."
            )
        else:
            details = "RAG analysis complete. No cycles detected — system is deadlock-free."

        return DeadlockResult(
            detected=detected,
            algorithm="Resource Allocation Graph (DFS Cycle Detection)",
            deadlocked_processes=list(deadlocked_pids),
            deadlocked_resources=list(deadlocked_rids),
            cycle_path=cycle_path,
            safe_sequence=[],
            timestamp=ts,
            details=details,
        )

    # ── Banker's Algorithm ────────────────────────────────────────────────────

    def _bankers_detection(self, processes: dict, resources: dict, ts: str) -> DeadlockResult:
        """
        Dijkstra's Banker's Algorithm safety check.

        Builds Allocation, Need, and Available matrices and simulates
        process completion to find a safe execution sequence.
        An unsafe state implies potential deadlock.
        """
        rids = list(resources.keys())
        pids = list(processes.keys())

        # Available vector
        available = {rid: resources[rid]["available"] for rid in rids}

        # Allocation matrix
        allocation = {
            pid: {rid: processes[pid].get("allocated", {}).get(rid, 0) for rid in rids}
            for pid in pids
        }

        # Max-need matrix (use allocated + requested as proxy if max_need not set)
        max_need = {}
        for pid in pids:
            p = processes[pid]
            mn = p.get("max_need", {})
            max_need[pid] = {
                rid: mn.get(rid, allocation[pid][rid] + p.get("requested", {}).get(rid, 0))
                for rid in rids
            }

        # Need matrix = Max − Allocation
        need = {
            pid: {rid: max(0, max_need[pid][rid] - allocation[pid][rid]) for rid in rids}
            for pid in pids
        }

        # Safety algorithm simulation
        work = dict(available)
        finish = {pid: False for pid in pids}
        safe_sequence = []
        changed = True

        while changed:
            changed = False
            for pid in pids:
                if finish[pid]:
                    continue
                if all(need[pid][rid] <= work.get(rid, 0) for rid in rids):
                    # Process can complete
                    for rid in rids:
                        work[rid] = work.get(rid, 0) + allocation[pid].get(rid, 0)
                    finish[pid] = True
                    safe_sequence.append(pid)
                    changed = True

        deadlocked = [pid for pid in pids if not finish[pid]]
        deadlocked_rids: List[str] = []

        if deadlocked:
            for pid in deadlocked:
                for rid, cnt in processes[pid].get("requested", {}).items():
                    if cnt > 0:
                        deadlocked_rids.append(rid)
            deadlocked_rids = list(set(deadlocked_rids))
            details = (
                f"Banker's algorithm found UNSAFE state. "
                f"{len(deadlocked)} process(es) cannot complete. "
                f"Safe sequence for remaining: {' → '.join(processes[p]['name'] for p in safe_sequence) or 'none'}"
            )
        else:
            details = (
                f"Banker's algorithm: SAFE state. "
                f"Safe sequence: {' → '.join(processes[p]['name'] for p in safe_sequence)}"
            )

        return DeadlockResult(
            detected=bool(deadlocked),
            algorithm="Banker's Algorithm (Safety Check)",
            deadlocked_processes=deadlocked,
            deadlocked_resources=deadlocked_rids,
            cycle_path=[],
            safe_sequence=[processes[p]["name"] for p in safe_sequence],
            timestamp=ts,
            details=details,
        )

    # ── Wait-For Graph ────────────────────────────────────────────────────────

    def _wfg_detection(self, processes: dict, resources: dict, ts: str) -> DeadlockResult:
        """
        Wait-For Graph — a simplified RAG that only includes process nodes.
        P_i → P_j if P_i is waiting for a resource held by P_j.
        Faster than RAG for process-heavy systems.
        """
        # Build resource → holding processes map
        holder: Dict[str, List[str]] = {rid: [] for rid in resources}
        for pid, p in processes.items():
            for rid in p.get("allocated", {}):
                holder.setdefault(rid, []).append(pid)

        # Build WFG adjacency
        wfg: Dict[str, List[str]] = {pid: [] for pid in processes}
        for pid, p in processes.items():
            for rid in p.get("requested", {}):
                for hpid in holder.get(rid, []):
                    if hpid != pid:
                        wfg[pid].append(hpid)

        # DFS on WFG
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cycles: List[List[str]] = []
        parent: Dict[str, str] = {}

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for nb in wfg.get(node, []):
                if nb not in visited:
                    parent[nb] = node
                    if dfs(nb):
                        return True
                elif nb in rec_stack:
                    cycle = [nb]
                    cur = node
                    while cur != nb:
                        cycle.append(cur)
                        cur = parent.get(cur, nb)
                    cycle.append(nb)
                    cycle.reverse()
                    cycles.append(cycle)
                    return True
            rec_stack.discard(node)
            return False

        for pid in list(processes.keys()):
            if pid not in visited:
                parent[pid] = pid
                dfs(pid)

        deadlocked_pids = set()
        cycle_path = []
        for cycle in cycles:
            for pid in cycle:
                deadlocked_pids.add(pid)
            labels = [processes[pid]["name"] for pid in cycle if pid in processes]
            cycle_path.append(" ⇒ ".join(labels))

        detected = bool(cycles)
        details = (
            f"WFG analysis found {len(cycles)} wait-cycle(s) among {len(deadlocked_pids)} process(es)."
            if detected else
            "WFG analysis: no circular waits detected."
        )

        return DeadlockResult(
            detected=detected,
            algorithm="Wait-For Graph (Process-Only Cycle Detection)",
            deadlocked_processes=list(deadlocked_pids),
            deadlocked_resources=[],
            cycle_path=cycle_path,
            safe_sequence=[],
            timestamp=ts,
            details=details,
        )
