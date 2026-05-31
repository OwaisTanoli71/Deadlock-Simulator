"""
Deadlock Detection & Recovery Simulator — Main GUI
───────────────────────────────────────────────────
Full Tkinter interface with:
  • Resource Allocation Graph canvas (live updating)
  • Control panel: add/remove processes & resources
  • Scenario loader
  • Detection panel: RAG / Banker's / WFG algorithms
  • Recovery panel: 4 strategies with step-by-step log
  • Event log panel
  • Status bar
"""

import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import threading
import time
import sys
import os

# Make sure imports work from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_manager import ResourceManager
from core.deadlock_detector import DeadlockDetector, DeadlockResult
from core.recovery_engine import RecoveryEngine
from core.simulation_engine import SimulationEngine
from gui.graph_renderer import GraphRenderer


# ── Palette ──────────────────────────────────────────────────────────────────
BG_DARK   = "#0d1117"
BG_PANEL  = "#161b22"
BG_CARD   = "#21262d"
BG_INPUT  = "#2d333b"
ACCENT    = "#00b4d8"
ACCENT2   = "#7ee787"
WARN      = "#f39c12"
DANGER    = "#e74c3c"
TEXT_PRI  = "#e6edf3"
TEXT_SEC  = "#8b949e"
BORDER    = "#30363d"
SUCCESS   = "#2ecc71"


class DeadlockSimulatorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("⚙ Deadlock Detection & Recovery Simulator")
        self.geometry("1400x860")
        self.minsize(1100, 700)
        self.configure(bg=BG_DARK)
        self._setup_style()

        # Core components
        self.manager   = ResourceManager()
        self.detector  = DeadlockDetector()
        self.recovery  = RecoveryEngine()
        self.sim       = SimulationEngine(self.manager, self._on_sim_event)
        self.renderer: GraphRenderer = None

        self._last_detection: DeadlockResult = None
        self._auto_detect = tk.BooleanVar(value=True)
        self._graph_mode  = tk.StringVar(value="rag")
        self._pid_counter = [1]
        self._rid_counter = [1]

        self._build_ui()
        self._start_refresh_loop()

    # ── Style ─────────────────────────────────────────────────────────────────

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        opts = {"background": BG_PANEL, "foreground": TEXT_PRI,
                "fieldbackground": BG_INPUT, "bordercolor": BORDER,
                "darkcolor": BG_DARK, "lightcolor": BG_CARD,
                "troughcolor": BG_INPUT, "selectbackground": ACCENT,
                "selectforeground": BG_DARK}
        for widget in ("TFrame","TLabel","TButton","TEntry","TCombobox",
                       "TLabelframe","TLabelframe.Label","TCheckbutton","TRadiobutton"):
            try:
                style.configure(widget, **{k:v for k,v in opts.items() if k in
                    style.element_options(widget.split(".")[0])})
            except Exception:
                pass
        style.configure("TButton", padding=6, relief="flat",
                         background=BG_CARD, foreground=TEXT_PRI, borderwidth=1)
        style.map("TButton", background=[("active", ACCENT)],
                             foreground=[("active", BG_DARK)])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG_DARK)
        style.map("Accent.TButton", background=[("active","#0096b7")])
        style.configure("Danger.TButton", background=DANGER, foreground="white")
        style.map("Danger.TButton", background=[("active","#c0392b")])
        style.configure("Success.TButton", background=SUCCESS, foreground=BG_DARK)
        style.map("Success.TButton", background=[("active","#27ae60")])
        style.configure("Warn.TButton", background=WARN, foreground=BG_DARK)
        style.map("Warn.TButton", background=[("active","#e67e22")])
        style.configure("TNotebook", background=BG_DARK, tabmargins=[2,2,2,0])
        style.configure("TNotebook.Tab", background=BG_CARD, foreground=TEXT_SEC,
                         padding=[10,4])
        style.map("TNotebook.Tab", background=[("selected",BG_PANEL)],
                                   foreground=[("selected",ACCENT)])

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG_PANEL, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚙  DEADLOCK DETECTION & RECOVERY SIMULATOR",
                 bg=BG_PANEL, fg=ACCENT,
                 font=("Consolas", 14, "bold")).pack(side="left", padx=18, pady=14)
        tk.Label(hdr, text="OS-Level Resource Management Engine",
                 bg=BG_PANEL, fg=TEXT_SEC,
                 font=("Segoe UI", 9)).pack(side="left", pady=14)

        # Status bar
        self._status_var = tk.StringVar(value="Ready")
        sb = tk.Frame(self, bg=BG_DARK, height=26)
        sb.pack(fill="x", side="bottom")
        tk.Label(sb, textvariable=self._status_var, bg=BG_DARK, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left", padx=10)
        self._deadlock_indicator = tk.Label(sb, text="● NO DEADLOCK",
                                            bg=BG_DARK, fg=SUCCESS,
                                            font=("Consolas", 8, "bold"))
        self._deadlock_indicator.pack(side="right", padx=14)

        # Main pane
        main = tk.PanedWindow(self, orient="horizontal", bg=BG_DARK,
                               sashwidth=5, sashrelief="flat")
        main.pack(fill="both", expand=True, padx=4, pady=(0,4))

        # Left control panel
        left = tk.Frame(main, bg=BG_PANEL, width=310)
        left.pack_propagate(False)
        main.add(left, minsize=260)
        self._build_left_panel(left)

        # Center: graph
        center = tk.Frame(main, bg=BG_DARK)
        main.add(center, minsize=500)
        self._build_graph_panel(center)

        # Right: detection + recovery + log
        right = tk.Frame(main, bg=BG_PANEL, width=360)
        right.pack_propagate(False)
        main.add(right, minsize=320)
        self._build_right_panel(right)

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left_panel(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        self._build_process_tab(nb)
        self._build_resource_tab(nb)
        self._build_scenario_tab(nb)
        self._build_alloc_tab(nb)

    def _build_process_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Processes")
        self._section(f, "Add Process")

        row = ttk.Frame(f); row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="Name:").pack(side="left")
        self._pname_var = tk.StringVar(value="Process-1")
        ttk.Entry(row, textvariable=self._pname_var, width=14).pack(side="right")

        row2 = ttk.Frame(f); row2.pack(fill="x", padx=8, pady=2)
        ttk.Label(row2, text="Priority (1-5):").pack(side="left")
        self._ppri_var = tk.IntVar(value=2)
        ttk.Spinbox(row2, from_=1, to=5, textvariable=self._ppri_var, width=4).pack(side="right")

        ttk.Button(f, text="➕ Add Process", style="Accent.TButton",
                   command=self._add_process).pack(fill="x", padx=8, pady=4)

        self._section(f, "Active Processes")
        self._proc_list = tk.Listbox(f, bg=BG_INPUT, fg=TEXT_PRI,
                                      selectbackground=ACCENT, height=8,
                                      font=("Consolas", 8), borderwidth=0)
        self._proc_list.pack(fill="both", expand=True, padx=8, pady=(0,4))

        btn_row = ttk.Frame(f); btn_row.pack(fill="x", padx=8, pady=2)
        ttk.Button(btn_row, text="✗ Terminate", style="Danger.TButton",
                   command=lambda: self._terminate_selected()).pack(side="left", expand=True, fill="x", padx=(0,2))
        ttk.Button(btn_row, text="↩ Rollback", style="Warn.TButton",
                   command=lambda: self._rollback_selected()).pack(side="right", expand=True, fill="x", padx=(2,0))

    def _build_resource_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Resources")
        self._section(f, "Add Resource")

        row = ttk.Frame(f); row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="Name:").pack(side="left")
        self._rname_var = tk.StringVar(value="Mutex-1")
        ttk.Entry(row, textvariable=self._rname_var, width=14).pack(side="right")

        row2 = ttk.Frame(f); row2.pack(fill="x", padx=8, pady=2)
        ttk.Label(row2, text="Instances:").pack(side="left")
        self._rinst_var = tk.IntVar(value=1)
        ttk.Spinbox(row2, from_=1, to=10, textvariable=self._rinst_var, width=4).pack(side="right")

        row3 = ttk.Frame(f); row3.pack(fill="x", padx=8, pady=2)
        ttk.Label(row3, text="Type:").pack(side="left")
        self._rtype_var = tk.StringVar(value="mutex")
        ttk.Combobox(row3, textvariable=self._rtype_var, width=12,
                     values=["mutex","semaphore","file","device"]).pack(side="right")

        ttk.Button(f, text="➕ Add Resource", style="Accent.TButton",
                   command=self._add_resource).pack(fill="x", padx=8, pady=4)

        self._section(f, "Active Resources")
        self._res_list = tk.Listbox(f, bg=BG_INPUT, fg=TEXT_PRI,
                                     selectbackground=ACCENT, height=8,
                                     font=("Consolas", 8), borderwidth=0)
        self._res_list.pack(fill="both", expand=True, padx=8, pady=(0,4))

    def _build_scenario_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Scenarios")
        self._section(f, "Preset Scenarios")

        scenarios = [
            ("dining_philosophers", "🍝 Dining Philosophers"),
            ("bankers_classic",     "🏦 Banker's Classic"),
            ("producer_consumer",   "📦 Producer-Consumer"),
            ("readers_writers",     "📖 Readers-Writers"),
            ("random_chaos",        "🎲 Random Chaos"),
        ]
        self._scenario_var = tk.StringVar(value="dining_philosophers")
        for val, label in scenarios:
            ttk.Radiobutton(f, text=label, variable=self._scenario_var,
                            value=val).pack(anchor="w", padx=12, pady=2)

        ttk.Button(f, text="📂 Load Scenario", style="Accent.TButton",
                   command=self._load_scenario).pack(fill="x", padx=8, pady=4)
        ttk.Button(f, text="▶ Run Simulation Steps", style="Success.TButton",
                   command=self._run_simulation).pack(fill="x", padx=8, pady=2)
        ttk.Button(f, text="⏹ Stop", command=self._stop_simulation
                   ).pack(fill="x", padx=8, pady=2)

        self._section(f, "Simulation Speed")
        spd_row = ttk.Frame(f); spd_row.pack(fill="x", padx=8, pady=2)
        ttk.Label(spd_row, text="Delay (s):").pack(side="left")
        self._speed_var = tk.DoubleVar(value=0.6)
        ttk.Scale(spd_row, from_=0.1, to=2.0, variable=self._speed_var,
                  orient="horizontal",
                  command=lambda v: self.sim.set_speed(float(v))).pack(side="right", fill="x", expand=True)

        self._section(f, "Clear")
        ttk.Button(f, text="🗑 Clear Everything", style="Danger.TButton",
                   command=self._clear_all).pack(fill="x", padx=8, pady=4)

    def _build_alloc_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Allocate")
        self._section(f, "Manual Allocation")

        row = ttk.Frame(f); row.pack(fill="x", padx=8, pady=3)
        ttk.Label(row, text="Process:").pack(side="left")
        self._alloc_pid = tk.StringVar()
        self._alloc_pid_cb = ttk.Combobox(row, textvariable=self._alloc_pid, width=14)
        self._alloc_pid_cb.pack(side="right")

        row2 = ttk.Frame(f); row2.pack(fill="x", padx=8, pady=3)
        ttk.Label(row2, text="Resource:").pack(side="left")
        self._alloc_rid = tk.StringVar()
        self._alloc_rid_cb = ttk.Combobox(row2, textvariable=self._alloc_rid, width=14)
        self._alloc_rid_cb.pack(side="right")

        row3 = ttk.Frame(f); row3.pack(fill="x", padx=8, pady=3)
        ttk.Label(row3, text="Count:").pack(side="left")
        self._alloc_count = tk.IntVar(value=1)
        ttk.Spinbox(row3, from_=1, to=10, textvariable=self._alloc_count, width=5).pack(side="right")

        ttk.Button(f, text="🔒 Request Resource", style="Accent.TButton",
                   command=self._manual_request).pack(fill="x", padx=8, pady=4)
        ttk.Button(f, text="🔓 Release Resource",
                   command=self._manual_release).pack(fill="x", padx=8, pady=2)

    # ── Graph panel ───────────────────────────────────────────────────────────

    def _build_graph_panel(self, parent):
        ctrl = tk.Frame(parent, bg=BG_DARK)
        ctrl.pack(fill="x", padx=4, pady=(4,0))

        tk.Label(ctrl, text="Graph View:", bg=BG_DARK, fg=TEXT_SEC,
                 font=("Segoe UI",9)).pack(side="left", padx=4)
        for val, label in [("rag","Resource Alloc Graph"),("wfg","Wait-For Graph")]:
            tk.Radiobutton(ctrl, text=label, variable=self._graph_mode, value=val,
                           bg=BG_DARK, fg=TEXT_PRI, selectcolor=BG_PANEL,
                           activebackground=BG_DARK,
                           command=self._refresh_graph).pack(side="left", padx=4)

        tk.Checkbutton(ctrl, text="Auto-detect on change",
                       variable=self._auto_detect,
                       bg=BG_DARK, fg=TEXT_PRI, selectcolor=BG_PANEL,
                       activebackground=BG_DARK).pack(side="right", padx=8)

        self._graph_canvas = tk.Canvas(parent, bg="#0a0e14", highlightthickness=0)
        self._graph_canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.renderer = GraphRenderer(self._graph_canvas)

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right_panel(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        self._build_detection_tab(nb)
        self._build_recovery_tab(nb)
        self._build_log_tab(nb)

    def _build_detection_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="🔍 Detection")

        self._section(f, "Algorithm")
        self._algo_var = tk.StringVar(value="rag")
        for val, label, desc in [
            ("rag",     "Resource Allocation Graph", "DFS cycle detection"),
            ("bankers", "Banker's Algorithm",        "Safety state analysis"),
            ("wfg",     "Wait-For Graph",            "Process-only cycles"),
        ]:
            row = ttk.Frame(f); row.pack(fill="x", padx=8, pady=1)
            ttk.Radiobutton(row, text=label, variable=self._algo_var, value=val).pack(side="left")
            ttk.Label(row, text=f"  ({desc})", foreground=TEXT_SEC,
                      font=("Segoe UI",7)).pack(side="left")

        ttk.Button(f, text="🔍 Run Detection", style="Accent.TButton",
                   command=self._run_detection).pack(fill="x", padx=8, pady=6)

        self._section(f, "Result")
        self._det_result_frame = tk.Frame(f, bg=BG_CARD, relief="flat")
        self._det_result_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self._det_result_text = tk.Text(self._det_result_frame, bg=BG_INPUT, fg=TEXT_PRI,
                                         font=("Consolas",8), wrap="word",
                                         state="disabled", borderwidth=0, height=10)
        self._det_result_text.pack(fill="both", expand=True, padx=2, pady=2)
        self._det_result_text.tag_config("ok",    foreground=SUCCESS)
        self._det_result_text.tag_config("bad",   foreground=DANGER)
        self._det_result_text.tag_config("warn",  foreground=WARN)
        self._det_result_text.tag_config("head",  foreground=ACCENT, font=("Consolas",9,"bold"))
        self._det_result_text.tag_config("cycle", foreground="#d63031")

    def _build_recovery_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="🛠 Recovery")

        self._section(f, "Strategy")
        self._rec_var = tk.StringVar(value="terminate")
        strategies = [
            ("terminate", "Kill Victim",       "Terminate lowest-priority process",      "Danger.TButton"),
            ("preempt",   "Preempt Resource",  "Steal resource from a waiting process",   "Warn.TButton"),
            ("rollback",  "Rollback Process",  "Reset victim, release its resources",     "Success.TButton"),
            ("kill_all",  "Kill All",          "Terminate every deadlocked process",      "Danger.TButton"),
        ]
        self._rec_buttons = {}
        for val, label, desc, style in strategies:
            row = ttk.Frame(f); row.pack(fill="x", padx=8, pady=2)
            btn = ttk.Button(row, text=label, style=style, width=14,
                             command=lambda v=val: self._run_recovery(v))
            btn.pack(side="left")
            ttk.Label(row, text=desc, foreground=TEXT_SEC,
                      font=("Segoe UI",7)).pack(side="left", padx=6)
            self._rec_buttons[val] = btn

        self._section(f, "Recovery Log")
        self._rec_text = tk.Text(f, bg=BG_INPUT, fg=TEXT_PRI, font=("Consolas",8),
                                  wrap="word", state="disabled", borderwidth=0, height=14)
        self._rec_text.pack(fill="both", expand=True, padx=8, pady=4)
        self._rec_text.tag_config("step",    foreground=ACCENT2)
        self._rec_text.tag_config("success", foreground=SUCCESS)
        self._rec_text.tag_config("error",   foreground=DANGER)
        self._rec_text.tag_config("cost",    foreground=WARN)
        self._rec_text.tag_config("head",    foreground=ACCENT, font=("Consolas",9,"bold"))

    def _build_log_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="📋 Event Log")

        self._log_text = tk.Text(f, bg=BG_INPUT, fg=TEXT_PRI, font=("Consolas",8),
                                  wrap="word", state="disabled", borderwidth=0)
        scroll = ttk.Scrollbar(f, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self._log_text.tag_config("allocate",  foreground=ACCENT2)
        self._log_text.tag_config("request",   foreground=WARN)
        self._log_text.tag_config("release",   foreground=ACCENT)
        self._log_text.tag_config("terminate", foreground=DANGER)
        self._log_text.tag_config("rollback",  foreground="#9b59b6")
        self._log_text.tag_config("scenario",  foreground="#00b4d8")
        self._log_text.tag_config("default",   foreground=TEXT_SEC)

        ttk.Button(f, text="🗑 Clear Log",
                   command=self._clear_log).pack(fill="x", padx=4, pady=(0,4))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG_PANEL)
        f.pack(fill="x", padx=8, pady=(8,2))
        tk.Label(f, text=title.upper(), bg=BG_PANEL, fg=ACCENT,
                 font=("Consolas",8,"bold")).pack(anchor="w")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=8)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _add_process(self):
        name = self._pname_var.get().strip() or f"Process-{self._pid_counter[0]}"
        pri  = self._ppri_var.get()
        pid  = f"P{self._pid_counter[0]}"
        self._pid_counter[0] += 1
        self.manager.add_process(pid, name, pri)
        self._pname_var.set(f"Process-{self._pid_counter[0]}")
        self._refresh()

    def _add_resource(self):
        name = self._rname_var.get().strip() or f"Resource-{self._rid_counter[0]}"
        inst = self._rinst_var.get()
        rtype= self._rtype_var.get()
        rid  = f"R{self._rid_counter[0]}"
        self._rid_counter[0] += 1
        self.manager.add_resource(rid, name, inst, rtype)
        self._rname_var.set(f"Mutex-{self._rid_counter[0]}")
        self._refresh()

    def _terminate_selected(self):
        sel = self._proc_list.curselection()
        if not sel:
            return
        text = self._proc_list.get(sel[0])
        pid  = text.split()[0]
        self.manager.terminate_process(pid, "manual")
        self._refresh()

    def _rollback_selected(self):
        sel = self._proc_list.curselection()
        if not sel:
            return
        text = self._proc_list.get(sel[0])
        pid  = text.split()[0]
        self.manager.rollback_process(pid)
        self._refresh()

    def _load_scenario(self):
        name = self._scenario_var.get()
        self._pid_counter[0] = 1
        self._rid_counter[0] = 1
        self.sim.load_scenario(name)
        self._refresh()
        self._status(f"Scenario loaded: {name}")

    def _run_simulation(self):
        name = self._scenario_var.get()
        self.sim.set_speed(self._speed_var.get())
        self.sim.run_scenario_steps(name)

    def _stop_simulation(self):
        self.sim.stop()

    def _clear_all(self):
        self.sim.stop()
        self.manager.clear_all()
        self._last_detection = None
        self._pid_counter[0] = 1
        self._rid_counter[0] = 1
        self._refresh()
        self._status("Cleared.")

    def _manual_request(self):
        pid = self._alloc_pid.get().split()[0] if self._alloc_pid.get() else ""
        rid = self._alloc_rid.get().split()[0] if self._alloc_rid.get() else ""
        cnt = self._alloc_count.get()
        if pid and rid:
            self.manager.request_resource(pid, rid, cnt)
            self._refresh()

    def _manual_release(self):
        pid = self._alloc_pid.get().split()[0] if self._alloc_pid.get() else ""
        rid = self._alloc_rid.get().split()[0] if self._alloc_rid.get() else ""
        cnt = self._alloc_count.get()
        if pid and rid:
            self.manager.release_resource(pid, rid, cnt)
            self._refresh()

    def _run_detection(self):
        algo   = self._algo_var.get()
        snap   = self.manager.get_snapshot()
        result = self.detector.detect(snap, algo)
        self._last_detection = result
        self._show_detection_result(result)
        self._update_status_bar(result)
        self._refresh_graph()

    def _run_recovery(self, strategy: str):
        if not self._last_detection:
            # Auto-detect first
            snap = self.manager.get_snapshot()
            self._last_detection = self.detector.detect(snap, self._algo_var.get())

        action = self.recovery.recover(self.manager, self._last_detection, strategy)
        self._show_recovery_result(action)
        self._last_detection = None   # reset after recovery
        self._refresh()

    # ── Display helpers ───────────────────────────────────────────────────────

    def _show_detection_result(self, result: DeadlockResult):
        t = self._det_result_text
        t.configure(state="normal")
        t.delete("1.0", "end")

        t.insert("end", f"[{result.timestamp}] {result.algorithm}\n", "head")
        t.insert("end", "─" * 40 + "\n", "head")

        if result.detected:
            t.insert("end", "⚠ DEADLOCK DETECTED!\n\n", "bad")
            t.insert("end", f"Deadlocked processes ({len(result.deadlocked_processes)}):\n", "warn")
            snap = self.manager.get_snapshot()
            for pid in result.deadlocked_processes:
                pname = snap["processes"].get(pid, {}).get("name", pid)
                t.insert("end", f"  • {pid} — {pname}\n", "bad")
            if result.deadlocked_resources:
                t.insert("end", f"\nContested resources ({len(result.deadlocked_resources)}):\n", "warn")
                for rid in result.deadlocked_resources:
                    rname = snap["resources"].get(rid, {}).get("name", rid)
                    t.insert("end", f"  • {rid} — {rname}\n", "bad")
            if result.cycle_path:
                t.insert("end", "\nCycle(s) detected:\n", "warn")
                for c in result.cycle_path:
                    t.insert("end", f"  ↻ {c}\n", "cycle")
            if result.safe_sequence:
                t.insert("end", f"\nPartial safe sequence: {' → '.join(result.safe_sequence)}\n", "warn")
        else:
            t.insert("end", "✓ No deadlock detected\n\n", "ok")
            if result.safe_sequence:
                t.insert("end", f"Safe sequence:\n  {' → '.join(result.safe_sequence)}\n", "ok")

        t.insert("end", f"\n{result.details}\n")
        t.configure(state="disabled")

    def _show_recovery_result(self, action):
        t = self._rec_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", f"[{action.timestamp}] {action.strategy}\n", "head")
        t.insert("end", "─" * 40 + "\n", "head")
        for step in action.steps:
            tag = "step"
            if "✗" in step or "error" in step.lower():
                tag = "error"
            elif "success" in step.lower() or "✓" in step:
                tag = "success"
            t.insert("end", step + "\n", tag)
        t.insert("end", f"\n💰 Cost: {action.cost_estimate}\n", "cost")
        t.configure(state="disabled")

    def _update_status_bar(self, result: DeadlockResult):
        if result.detected:
            self._deadlock_indicator.configure(
                text=f"● DEADLOCK ({len(result.deadlocked_processes)} proc)",
                fg=DANGER)
        else:
            self._deadlock_indicator.configure(text="● NO DEADLOCK", fg=SUCCESS)

    # ── Refresh loop ──────────────────────────────────────────────────────────

    def _start_refresh_loop(self):
        self._refresh_loop()

    def _refresh_loop(self):
        try:
            self._refresh()
        except Exception:
            pass
        self.after(1200, self._refresh_loop)

    def _refresh(self):
        snap = self.manager.get_snapshot()

        # Update process list
        self._proc_list.delete(0, "end")
        for pid, p in snap["processes"].items():
            state = p["state"]
            color = {"running":"#2ecc71","waiting":"#f39c12","blocked":"#e74c3c",
                     "terminated":"#95a5a6","rolled_back":"#9b59b6"}.get(state,"white")
            self._proc_list.insert("end",
                f"{pid} {p['name']:<16} [{state}] pri={p['priority']}")

        # Update resource list
        self._res_list.delete(0, "end")
        for rid, r in snap["resources"].items():
            self._res_list.insert("end",
                f"{rid} {r['name']:<16} {r['available']}/{r['total']} free")

        # Update comboboxes
        p_choices = [f"{pid} {p['name']}" for pid, p in snap["processes"].items()]
        r_choices = [f"{rid} {r['name']}" for rid, r in snap["resources"].items()]
        self._alloc_pid_cb["values"] = p_choices
        self._alloc_rid_cb["values"] = r_choices

        # Update log
        self._refresh_log(snap["events"])

        # Auto-detect
        if self._auto_detect.get():
            algo   = self._algo_var.get()
            result = self.detector.detect(snap, algo)
            if result.detected != (self._last_detection and self._last_detection.detected):
                self._last_detection = result
                self._show_detection_result(result)
            elif result.detected:
                self._last_detection = result
            self._update_status_bar(result)

        # Refresh graph
        self._refresh_graph()

    def _refresh_graph(self):
        snap   = self.manager.get_snapshot()
        mode   = self._graph_mode.get()
        result = self._last_detection
        if self.renderer:
            self.renderer.render(snap, result, mode)

    def _refresh_log(self, events):
        t = self._log_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for ev in reversed(events[-60:]):
            tag = ev.get("type", "default")
            t.insert("end", f"[{ev['timestamp']}] ", "default")
            t.insert("end", ev["message"] + "\n", tag)
        t.configure(state="disabled")

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _status(self, msg: str):
        self._status_var.set(msg)

    def _on_sim_event(self, event_type: str, message: str):
        self._status(message)


def main():
    app = DeadlockSimulatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
