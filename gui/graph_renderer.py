"""
Graph Renderer
──────────────
Renders the Resource Allocation Graph (RAG) and Wait-For Graph (WFG)
using NetworkX + Matplotlib, embedded inside the Tkinter GUI.
"""

import math
import tkinter as tk
from typing import Dict, List, Optional, Tuple
import threading


class GraphRenderer:
    """
    Draws the RAG on a Tkinter Canvas.

    Node types:
      • Circle  — Process  (colored by process color)
      • Square  — Resource (gray, subdivided by instance count)

    Edge types:
      • Blue  arrow  — allocation  (Resource → Process)
      • Red   arrow  — request     (Process  → Resource)
      • Amber arrow  — wait-for    (Process  → Process, WFG mode)

    Deadlocked nodes are highlighted with a red glow border.
    """

    NODE_RADIUS = 28
    RESOURCE_HALF = 24
    FONT_LABEL = ("Consolas", 8, "bold")
    FONT_NAME = ("Segoe UI", 7)

    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        self._positions: Dict[str, Tuple[float, float]] = {}
        self._node_items: Dict[str, List[int]] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def render(self, snapshot: dict, detection_result=None, mode: str = "rag"):
        """Redraw the entire graph on the canvas."""
        self.canvas.delete("all")
        processes = snapshot.get("processes", {})
        resources = snapshot.get("resources", {})

        if not processes and not resources:
            self._draw_empty()
            return

        deadlocked_pids = set()
        deadlocked_rids = set()
        if detection_result and detection_result.detected:
            deadlocked_pids = set(detection_result.deadlocked_processes)
            deadlocked_rids = set(detection_result.deadlocked_resources)

        # Compute layout
        positions = self._compute_layout(processes, resources)
        self._positions = positions

        # Draw edges first (below nodes)
        if mode == "wfg":
            self._draw_wfg_edges(processes, positions)
        else:
            self._draw_rag_edges(processes, resources, positions)

        # Draw nodes
        for pid, p in processes.items():
            x, y = positions.get(pid, (0, 0))
            self._draw_process_node(pid, p, x, y, pid in deadlocked_pids)

        for rid, r in resources.items():
            x, y = positions.get(rid, (0, 0))
            self._draw_resource_node(rid, r, x, y, rid in deadlocked_rids)

        # Legend
        self._draw_legend(mode)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _compute_layout(self, processes: dict, resources: dict) -> Dict[str, Tuple[float, float]]:
        """
        Two-ring layout:
          • Inner ring — processes
          • Outer ring — resources
        Falls back to single ring if only one type present.
        """
        w = int(self.canvas.winfo_width() or 700)
        h = int(self.canvas.winfo_height() or 500)
        cx, cy = w / 2, h / 2

        positions = {}
        pids = list(processes.keys())
        rids = list(resources.keys())

        r_inner = min(cx, cy) * 0.38
        r_outer = min(cx, cy) * 0.70

        for i, pid in enumerate(pids):
            angle = 2 * math.pi * i / max(len(pids), 1) - math.pi / 2
            positions[pid] = (cx + r_inner * math.cos(angle),
                              cy + r_inner * math.sin(angle))

        for i, rid in enumerate(rids):
            angle = 2 * math.pi * i / max(len(rids), 1) - math.pi / 2 + math.pi / max(len(rids), 1)
            positions[rid] = (cx + r_outer * math.cos(angle),
                              cy + r_outer * math.sin(angle))

        return positions

    # ── Edge drawing ──────────────────────────────────────────────────────────

    def _draw_rag_edges(self, processes: dict, resources: dict, pos: dict):
        for pid, p in processes.items():
            px, py = pos.get(pid, (0, 0))
            # Request edges: P → R  (red dashed)
            for rid in p.get("requested", {}):
                if rid in pos:
                    rx, ry = pos[rid]
                    self._arrow(px, py, rx, ry, "#e74c3c", dash=(5, 3), label="wants")

            # Allocation edges: R → P  (teal solid)
            for rid in p.get("allocated", {}):
                if rid in pos:
                    rx, ry = pos[rid]
                    self._arrow(rx, ry, px, py, "#00b4d8", label="holds")

    def _draw_wfg_edges(self, processes: dict, pos: dict):
        """WFG: P_i → P_j if P_i waits for resource held by P_j."""
        holder: Dict[str, List[str]] = {}
        for pid, p in processes.items():
            for rid in p.get("allocated", {}):
                holder.setdefault(rid, []).append(pid)

        for pid, p in processes.items():
            px, py = pos.get(pid, (0, 0))
            for rid in p.get("requested", {}):
                for hpid in holder.get(rid, []):
                    if hpid != pid and hpid in pos:
                        hx, hy = pos[hpid]
                        self._arrow(px, py, hx, hy, "#f39c12", label="waits-for")

    def _arrow(self, x1, y1, x2, y2, color, dash=None, label=""):
        """Draw an arrow from (x1,y1) to (x2,y2) with shortened endpoints."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1
        ux, uy = dx / length, dy / length
        # shorten start and end so arrows sit on node borders
        margin = self.NODE_RADIUS + 4
        sx, sy = x1 + ux * margin, y1 + uy * margin
        ex, ey = x2 - ux * (margin - 4), y2 - uy * (margin - 4)

        kw = {"fill": color, "width": 2, "arrow": tk.LAST,
              "arrowshape": (10, 12, 4)}
        if dash:
            kw["dash"] = dash
        self.canvas.create_line(sx, sy, ex, ey, **kw)

    # ── Node drawing ──────────────────────────────────────────────────────────

    def _draw_process_node(self, pid, p, x, y, deadlocked):
        r = self.NODE_RADIUS
        color = p.get("color", "#4ecdc4")
        state = p.get("state", "running")

        state_colors = {
            "running": color,
            "waiting": "#f39c12",
            "blocked": "#c0392b",
            "terminated": "#7f8c8d",
            "rolled_back": "#9b59b6",
        }
        fill = state_colors.get(state, color)

        # Glow for deadlocked
        if deadlocked:
            self.canvas.create_oval(x-r-6, y-r-6, x+r+6, y+r+6,
                                    fill="#c0392b", outline="", stipple="gray50")

        self.canvas.create_oval(x-r, y-r, x+r, y+r,
                                fill=fill, outline="white", width=2)
        self.canvas.create_text(x, y-6, text=pid, fill="white",
                                font=self.FONT_LABEL)
        self.canvas.create_text(x, y+8, text=p.get("name",""), fill="white",
                                font=self.FONT_NAME)
        # State dot
        sdot_colors = {"running":"#2ecc71","waiting":"#f39c12",
                       "blocked":"#e74c3c","terminated":"#95a5a6","rolled_back":"#9b59b6"}
        sdot = sdot_colors.get(state, "#95a5a6")
        self.canvas.create_oval(x+r-8, y-r, x+r+2, y-r+10,
                                fill=sdot, outline="white", width=1)

    def _draw_resource_node(self, rid, r, x, y, deadlocked):
        h = self.RESOURCE_HALF
        rtype_colors = {
            "mutex": "#2c3e50", "semaphore": "#1a5276",
            "file": "#145a32", "device": "#4a235a",
        }
        fill = rtype_colors.get(r.get("type", "mutex"), "#2c3e50")

        if deadlocked:
            self.canvas.create_rectangle(x-h-6, y-h-6, x+h+6, y+h+6,
                                         fill="#c0392b", outline="", stipple="gray50")

        self.canvas.create_rectangle(x-h, y-h, x+h, y+h,
                                     fill=fill, outline="white", width=2)
        self.canvas.create_text(x, y-8, text=rid, fill="white",
                                font=self.FONT_LABEL)
        self.canvas.create_text(x, y+4, text=r.get("name",""), fill="#bdc3c7",
                                font=self.FONT_NAME)
        # Instance dots
        total = r.get("total", 1)
        avail = r.get("available", 0)
        dot_r = 4
        spacing = 10
        start_x = x - (total - 1) * spacing / 2
        for i in range(total):
            dot_x = start_x + i * spacing
            dot_color = "#2ecc71" if i < avail else "#e74c3c"
            self.canvas.create_oval(dot_x-dot_r, y+12-dot_r,
                                    dot_x+dot_r, y+12+dot_r,
                                    fill=dot_color, outline="white")

    # ── Legend ────────────────────────────────────────────────────────────────

    def _draw_legend(self, mode: str):
        items = [
            ("#00b4d8", "─────", "Allocation (R→P)"),
            ("#e74c3c", "- - -", "Request (P→R)"),
            ("#f39c12", "─────", "Wait-For (P→P)"),
            ("#2ecc71", "●", "Instance available"),
            ("#e74c3c", "●", "Instance allocated"),
        ] if mode == "rag" else [
            ("#f39c12", "─────", "Wait-For (P→P)"),
        ]

        x, y = 12, 12
        for color, sym, label in items:
            self.canvas.create_text(x, y, text=sym, fill=color,
                                    font=("Consolas", 9), anchor="w")
            self.canvas.create_text(x+30, y, text=label, fill="#ecf0f1",
                                    font=("Segoe UI", 8), anchor="w")
            y += 16

    def _draw_empty(self):
        w = int(self.canvas.winfo_width() or 700)
        h = int(self.canvas.winfo_height() or 500)
        self.canvas.create_text(
            w//2, h//2,
            text="No processes or resources.\nAdd some or load a scenario.",
            fill="#7f8c8d", font=("Segoe UI", 13), justify="center",
        )
