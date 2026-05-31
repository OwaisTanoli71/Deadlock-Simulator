"""
Resource Manager — Core engine for tracking resource allocation and requests.
Models the OS resource allocation table used by deadlock detection algorithms.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import threading
import time
import random


@dataclass
class Resource:
    """Represents a system resource (e.g., mutex, semaphore, file handle)."""
    rid: str
    name: str
    total_instances: int
    available_instances: int
    resource_type: str = "mutex"  # mutex, semaphore, file, device

    @property
    def allocated_instances(self) -> int:
        return self.total_instances - self.available_instances

    def to_dict(self) -> dict:
        return {
            "rid": self.rid,
            "name": self.name,
            "total": self.total_instances,
            "available": self.available_instances,
            "allocated": self.allocated_instances,
            "type": self.resource_type,
        }


@dataclass
class Process:
    """Represents an OS process competing for resources."""
    pid: str
    name: str
    priority: int = 1          # 1=low … 5=high
    state: str = "running"     # running | waiting | blocked | terminated | rolled_back
    allocated: Dict[str, int] = field(default_factory=dict)   # rid -> count held
    requested: Dict[str, int] = field(default_factory=dict)   # rid -> count waiting for
    max_need: Dict[str, int] = field(default_factory=dict)    # Banker's algorithm max
    wait_time: float = 0.0
    created_at: float = field(default_factory=time.time)
    color: str = "#4ecdc4"

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "priority": self.priority,
            "state": self.state,
            "allocated": dict(self.allocated),
            "requested": dict(self.requested),
            "max_need": dict(self.max_need),
            "wait_time": round(self.wait_time, 2),
            "color": self.color,
        }


class ResourceManager:
    """
    Central OS resource manager.
    Tracks allocation state and provides the raw data needed by
    detection algorithms and the recovery engine.
    """

    PROCESS_COLORS = [
        "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
        "#1abc9c", "#e67e22", "#e91e63", "#00bcd4", "#8bc34a",
    ]

    def __init__(self):
        self.resources: Dict[str, Resource] = {}
        self.processes: Dict[str, Process] = {}
        self._lock = threading.Lock()
        self._event_log: List[dict] = []
        self._color_idx = 0

    # ── Resource management ──────────────────────────────────────────────────

    def add_resource(self, rid: str, name: str, instances: int,
                     rtype: str = "mutex") -> Resource:
        with self._lock:
            r = Resource(rid, name, instances, instances, rtype)
            self.resources[rid] = r
            self._log("add_resource", f"Resource {name} ({rid}) added with {instances} instance(s)")
            return r

    def remove_resource(self, rid: str) -> bool:
        with self._lock:
            if rid in self.resources and self.resources[rid].available_instances == self.resources[rid].total_instances:
                del self.resources[rid]
                self._log("remove_resource", f"Resource {rid} removed")
                return True
            return False

    # ── Process management ───────────────────────────────────────────────────

    def add_process(self, pid: str, name: str, priority: int = 1) -> Process:
        with self._lock:
            color = self.PROCESS_COLORS[self._color_idx % len(self.PROCESS_COLORS)]
            self._color_idx += 1
            p = Process(pid, name, priority, color=color)
            self.processes[pid] = p
            self._log("add_process", f"Process {name} ({pid}) created  priority={priority}")
            return p

    def terminate_process(self, pid: str, reason: str = "normal") -> bool:
        """Release all resources held by process and mark it terminated."""
        with self._lock:
            if pid not in self.processes:
                return False
            p = self.processes[pid]
            # release everything
            for rid, count in list(p.allocated.items()):
                if rid in self.resources:
                    self.resources[rid].available_instances += count
            p.allocated.clear()
            p.requested.clear()
            p.state = "terminated"
            self._log("terminate", f"Process {p.name} ({pid}) terminated  reason={reason}")
            return True

    def rollback_process(self, pid: str) -> bool:
        """Return all resources to pool but keep process alive (rolled back state)."""
        with self._lock:
            if pid not in self.processes:
                return False
            p = self.processes[pid]
            for rid, count in list(p.allocated.items()):
                if rid in self.resources:
                    self.resources[rid].available_instances += count
            p.allocated.clear()
            p.requested.clear()
            p.state = "rolled_back"
            self._log("rollback", f"Process {p.name} ({pid}) rolled back — resources released")
            return True

    # ── Allocation / request ─────────────────────────────────────────────────

    def request_resource(self, pid: str, rid: str, count: int = 1) -> bool:
        """
        Try to allocate `count` instances of `rid` to `pid`.
        Returns True on success, False if unavailable (process enters waiting).
        """
        with self._lock:
            if pid not in self.processes or rid not in self.resources:
                return False
            p = self.processes[pid]
            r = self.resources[rid]
            if r.available_instances >= count:
                r.available_instances -= count
                p.allocated[rid] = p.allocated.get(rid, 0) + count
                p.requested.pop(rid, None)
                p.state = "running"
                self._log("allocate", f"{p.name} allocated {count}× {r.name}")
                return True
            else:
                p.requested[rid] = count
                p.state = "waiting"
                self._log("request", f"{p.name} waiting for {count}× {r.name} (only {r.available_instances} free)")
                return False

    def release_resource(self, pid: str, rid: str, count: int = 1) -> bool:
        with self._lock:
            if pid not in self.processes or rid not in self.resources:
                return False
            p = self.processes[pid]
            r = self.resources[rid]
            held = p.allocated.get(rid, 0)
            release_count = min(count, held)
            if release_count == 0:
                return False
            r.available_instances += release_count
            p.allocated[rid] = held - release_count
            if p.allocated[rid] == 0:
                del p.allocated[rid]
            self._log("release", f"{p.name} released {release_count}× {r.name}")
            return True

    # ── State snapshot (thread-safe) ─────────────────────────────────────────

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "resources": {rid: r.to_dict() for rid, r in self.resources.items()},
                "processes": {pid: p.to_dict() for pid, p in self.processes.items()},
                "events": list(self._event_log[-50:]),
            }

    def get_allocation_matrix(self) -> dict:
        """Return matrices needed by Banker's / deadlock detection."""
        with self._lock:
            rids = list(self.resources.keys())
            pids = list(self.processes.keys())
            allocation = {pid: {rid: self.processes[pid].allocated.get(rid, 0) for rid in rids} for pid in pids}
            request = {pid: {rid: self.processes[pid].requested.get(rid, 0) for rid in rids} for pid in pids}
            available = {rid: self.resources[rid].available_instances for rid in rids}
            return {"pids": pids, "rids": rids, "allocation": allocation, "request": request, "available": available}

    def _log(self, event_type: str, message: str):
        self._event_log.append({
            "type": event_type,
            "message": message,
            "timestamp": time.strftime("%H:%M:%S"),
        })
        if len(self._event_log) > 500:
            self._event_log = self._event_log[-500:]

    def clear_all(self):
        with self._lock:
            self.resources.clear()
            self.processes.clear()
            self._event_log.clear()
            self._color_idx = 0
