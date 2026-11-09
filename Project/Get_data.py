import json
import math
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Callable

import matplotlib

matplotlib.use("TkAgg")

import psycopg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from DB import DB

ANY = "(any)"
DEFAULT_BIN_MS = 100   # probe samples are averaged into bins of this size

# --- Probe columns and how they are aggregated per bin ------------------------

TCP_AVG = [                       # gauges: averaged over the bin
    "cwnd", "ssthresh", "srtt_us", "rttvar_us", "inflight", "packets_out",
    "sacked_out", "lost_out", "retrans_out", "snd_wnd", "rcv_wnd", "pacing_bps",
    "wmem_queued", "sndbuf", "rto_j", "reordering",
]
TCP_MAX = ["ca_state", "backoff"]  # states: worst value in the bin
TCP_MIN = ["minrtt_us"]            # lowest value in the bin
TCP_COUNTERS = [                   # cumulative: first/last value in the bin -> deltas
    "bytes_acked", "bytes_retrans", "total_retrans", "lost", "delivered",
    "delivered_ce", "busy_j", "rwnd_lim_j", "sndbuf_lim_j",
]
CUBIC_COLUMNS = ["w_max", "k", "epoch_start", "cnt", "delay_min"]
IPERF_COLUMNS = ["throughput", "rtt_ms", "cwnd", "retrans"]


# --- Metric definitions ------------------------------------------------------

@dataclass(frozen=True)
class Metric:
    key: str
    group: str                          # heading in the sidebar
    label: str                          # sidebar text and y-axis label
    source: str                         # "tcp", "cubic" or "iperf"
    values: Callable[[dict], list]      # computes the series from that source's data
    default: bool = False               # checked when the viewer starts


def col(name: str, scale: float = 1.0):
    """A column as-is, multiplied by scale."""
    return lambda d: [v * scale for v in d[name]]


def ratio(numerators, denominators, scale: float = 100.0) -> list[float]:
    return [n / d * scale if d else math.nan for n, d in zip(numerators, denominators)]


def rate(counter: str, scale: float = 1.0):
    """Increase of a cumulative counter per second."""
    return lambda d: [
        x / dt * scale if dt > 0 else math.nan
        for x, dt in zip(d[f"d_{counter}"], d["dt"])
    ]


def chrono_share(part: str):
    """Share of the sender's time spent in one chrono state (busy, rwnd- or sndbuf-limited)."""
    def compute(d):
        total = [a + b + c for a, b, c in zip(d["d_busy_j"], d["d_rwnd_lim_j"], d["d_sndbuf_lim_j"])]
        return ratio(d[f"d_{part}"], total)
    return compute


KB = 1 / 1024
MBIT_FROM_BYTES = 8e-6

METRICS = [
    # Derived from several probe values
    Metric("goodput", "Derived", "Goodput (Mbit/s)", "tcp",
           rate("bytes_acked", MBIT_FROM_BYTES), default=True),
    Metric("retrans_overhead", "Derived", "Retransmission overhead (%)", "tcp",
           lambda d: ratio(d["d_bytes_retrans"],
                           [a + r for a, r in zip(d["d_bytes_acked"], d["d_bytes_retrans"])]),
           default=True),
    Metric("loss_rate", "Derived", "Loss rate (%)", "tcp",
           lambda d: ratio(d["d_lost"], d["d_delivered"])),
    Metric("queue_delay", "Derived", "Queueing delay (ms)", "tcp",
           lambda d: [(s - m) / 1000 for s, m in zip(d["avg_srtt_us"], d["min_minrtt_us"])],
           default=True),
    Metric("window_used", "Derived", "Window used (%)", "tcp",
           lambda d: ratio(d["avg_inflight"], d["avg_cwnd"])),
    Metric("rwnd_share", "Derived", "Receiver-limited share (%)", "tcp", chrono_share("rwnd_lim_j")),
    Metric("sndbuf_share", "Derived", "Send-buffer-limited share (%)", "tcp", chrono_share("sndbuf_lim_j")),

    # Probe values, averaged per bin
    Metric("cwnd", "TCP state", "cwnd (segments)", "tcp", col("avg_cwnd"), default=True),
    Metric("ssthresh", "TCP state", "ssthresh (segments)", "tcp", col("avg_ssthresh")),
    Metric("srtt", "TCP state", "Smoothed RTT (ms)", "tcp", col("avg_srtt_us", 1e-3)),
    Metric("rttvar", "TCP state", "RTT variation (ms)", "tcp", col("avg_rttvar_us", 1e-3)),
    Metric("minrtt", "TCP state", "Min RTT (ms)", "tcp", col("min_minrtt_us", 1e-3)),
    Metric("inflight", "TCP state", "In flight (packets)", "tcp", col("avg_inflight")),
    Metric("packets_out", "TCP state", "Packets out", "tcp", col("avg_packets_out")),
    Metric("sacked_out", "TCP state", "SACKed out (packets)", "tcp", col("avg_sacked_out")),
    Metric("lost_out", "TCP state", "Lost out (packets)", "tcp", col("avg_lost_out")),
    Metric("retrans_out", "TCP state", "Retrans out (packets)", "tcp", col("avg_retrans_out")),
    Metric("snd_wnd", "TCP state", "Receiver window (KB)", "tcp", col("avg_snd_wnd", KB)),
    Metric("rcv_wnd", "TCP state", "Own receive window (KB)", "tcp", col("avg_rcv_wnd", KB)),
    Metric("pacing", "TCP state", "Pacing rate (Mbit/s)", "tcp", col("avg_pacing_bps", MBIT_FROM_BYTES)),
    Metric("wmem_queued", "TCP state", "Send buffer used (KB)", "tcp", col("avg_wmem_queued", KB)),
    Metric("sndbuf", "TCP state", "Send buffer size (KB)", "tcp", col("avg_sndbuf", KB)),
    Metric("ca_state", "TCP state", "CA state (0 Open–4 Loss)", "tcp", col("max_ca_state")),
    Metric("backoff", "TCP state", "RTO backoff", "tcp", col("max_backoff")),
    Metric("rto", "TCP state", "RTO (jiffies)", "tcp", col("avg_rto_j")),
    Metric("reordering", "TCP state", "Reordering (packets)", "tcp", col("avg_reordering")),

    # Cumulative probe counters turned into rates
    Metric("retrans_rate", "Rates", "Retransmitted (Mbit/s)", "tcp", rate("bytes_retrans", MBIT_FROM_BYTES)),
    Metric("retrans_segs", "Rates", "Retransmitted segments (/s)", "tcp", rate("total_retrans")),
    Metric("lost_rate", "Rates", "Lost packets (/s)", "tcp", rate("lost")),
    Metric("delivered_rate", "Rates", "Delivered packets (/s)", "tcp", rate("delivered")),
    Metric("ce_rate", "Rates", "ECN CE-marked packets (/s)", "tcp", rate("delivered_ce")),

    # Cumulative probe counters as-is
    Metric("c_bytes_acked", "Counters (cumulative)", "Bytes ACKed (MB)", "tcp", col("last_bytes_acked", 1e-6)),
    Metric("c_bytes_retrans", "Counters (cumulative)", "Bytes retransmitted (MB)", "tcp", col("last_bytes_retrans", 1e-6)),
    Metric("c_total_retrans", "Counters (cumulative)", "Retransmitted segments", "tcp", col("last_total_retrans")),
    Metric("c_lost", "Counters (cumulative)", "Lost packets", "tcp", col("last_lost")),
    Metric("c_delivered", "Counters (cumulative)", "Delivered packets", "tcp", col("last_delivered")),
    Metric("c_delivered_ce", "Counters (cumulative)", "CE-marked packets", "tcp", col("last_delivered_ce")),
    Metric("c_busy", "Counters (cumulative)", "Busy time (jiffies)", "tcp", col("last_busy_j")),
    Metric("c_rwnd_lim", "Counters (cumulative)", "Rwnd-limited (jiffies)", "tcp", col("last_rwnd_lim_j")),
    Metric("c_sndbuf_lim", "Counters (cumulative)", "Sndbuf-limited (jiffies)", "tcp", col("last_sndbuf_lim_j")),

    # CUBIC internals
    Metric("w_max", "CUBIC", "W_max (segments)", "cubic", col("max_w_max")),
    Metric("k", "CUBIC", "K (s)", "cubic", col("max_k", 1 / 1024)),
    Metric("epoch_start", "CUBIC", "Epoch start (jiffies)", "cubic", col("max_epoch_start")),
    Metric("cnt", "CUBIC", "cnt (ACKs per +1 cwnd)", "cubic", col("max_cnt")),
    Metric("delay_min", "CUBIC", "CUBIC min delay (ms)", "cubic", col("max_delay_min", 1e-3)),

    # The iperf3 interval results (the old graphs)
    Metric("iperf_throughput", "iperf3 (per interval)", "iperf throughput (Mbit/s)", "iperf", col("throughput", 1e-6)),
    Metric("iperf_rtt", "iperf3 (per interval)", "iperf RTT (ms)", "iperf", col("rtt_ms")),
    Metric("iperf_cwnd", "iperf3 (per interval)", "iperf cwnd (KB)", "iperf", col("cwnd", KB)),
    Metric("iperf_retrans", "iperf3 (per interval)", "iperf retransmits", "iperf", col("retrans")),
]


# --- Data access -------------------------------------------------------------

def parm_float(test: dict, key: str, default: float) -> float:
    try:
        return float(test["parms"].get(key, default))
    except (TypeError, ValueError):
        return default


def to_columns(rows, names) -> dict[str, list[float]]:
    """Turn row tuples into {name: [float, ...]}."""
    return {
        name: [float(row[i]) if row[i] is not None else math.nan for row in rows]
        for i, name in enumerate(names)
    }


def fetch_tests() -> list[dict]:
    """Return every test as {"id", "name", "cca", "parms"}."""
    with DB() as database:
        rows = list(database.query("SELECT id, name, cca, parms FROM public.tests"))

    tests = []
    for test_id, test_name, cca, parms in rows:
        if isinstance(parms, str):  # json stored as text; jsonb usually arrives as a dict already
            parms = json.loads(parms)
        tests.append({"id": test_id, "name": test_name, "cca": cca, "parms": parms or {}})
    return tests


def fetch_iperf(database, test: dict) -> dict:
    rows = database.query(
        f"SELECT {', '.join(IPERF_COLUMNS)} FROM public.results WHERE test_id = %s ORDER BY id",
        (test["id"],),
    ) or []
    data = to_columns(rows, IPERF_COLUMNS)
    interval = parm_float(test, "interval", 1.0) or 1.0
    data["t"] = [(i + 1) * interval for i in range(len(rows))]
    return data


def add_bin_times(data: dict, bin_ns: int) -> None:
    """Bin numbers -> time at the end of each bin (s), and each bin's span since the previous one."""
    bin_s = bin_ns / 1e9
    bins = data["bin"]
    data["t"] = [(b + 1) * bin_s for b in bins]
    data["dt"] = [bin_s if i == 0 else (b - bins[i - 1]) * bin_s for i, b in enumerate(bins)]


def fetch_tcp(database, test_id, t0: int, bin_ns: int, where: str, params: dict) -> dict:
    names, select = ["bin"], ["(t_ns - %(t0)s) / %(bin)s"]
    for c in TCP_AVG:
        names.append(f"avg_{c}"); select.append(f"avg({c})")
    for c in TCP_MAX:
        names.append(f"max_{c}"); select.append(f"max({c})")
    for c in TCP_MIN:
        names.append(f"min_{c}"); select.append(f"min({c})")
    for c in TCP_COUNTERS:
        names += [f"first_{c}", f"last_{c}"]; select += [f"min({c})", f"max({c})"]

    rows = database.query(
        f"""
        SELECT {', '.join(select)}
        FROM public.tcp_samples
        WHERE test_id = %(id)s AND {where}
        GROUP BY 1
        ORDER BY 1
        """,
        {**params, "id": test_id, "t0": t0, "bin": bin_ns},
    ) or []
    data = to_columns(rows, names)
    add_bin_times(data, bin_ns)

    # Increase of each counter since the previous bin (first bin: within itself)
    for c in TCP_COUNTERS:
        first, last = data[f"first_{c}"], data[f"last_{c}"]
        data[f"d_{c}"] = [
            last[i] - (first[i] if i == 0 else last[i - 1]) for i in range(len(last))
        ]
    return data


def fetch_cubic(database, test_id, t0: int, bin_ns: int, where: str, params: dict) -> dict:
    names = ["bin"] + [f"max_{c}" for c in CUBIC_COLUMNS]
    select = ["(t_ns - %(t0)s) / %(bin)s"] + [f"max({c})" for c in CUBIC_COLUMNS]
    rows = database.query(
        f"""
        SELECT {', '.join(select)}
        FROM public.cubic_samples
        WHERE test_id = %(id)s AND {where}
        GROUP BY 1
        ORDER BY 1
        """,
        {**params, "id": test_id, "t0": t0, "bin": bin_ns},
    ) or []
    data = to_columns(rows, names)
    add_bin_times(data, bin_ns)
    return data


def data_connection_filters(database, test_id) -> tuple[str, str, dict]:
    """SQL conditions that keep only the iperf3 data connection.

    The probe also sees iperf3's control connection (same server port).
    Mixing the two breaks the counters, e.g. a hugely negative goodput.
    - Logs with a sport column: keep the socket that ACKed the most bytes.
    - Older logs without sport: drop samples whose bytes_acked is below
      0.1 % of the maximum (the control connection only sends a few KB).
    Returns (tcp_where, cubic_where, params).
    """
    sport, max_acked = database.query(
        """
        SELECT (SELECT sport FROM public.tcp_samples
                WHERE test_id = %(id)s AND sport IS NOT NULL
                ORDER BY bytes_acked DESC LIMIT 1),
               max(bytes_acked)
        FROM public.tcp_samples WHERE test_id = %(id)s
        """,
        {"id": test_id},
    )[0]
    if sport is not None:
        # CUBIC logs without a sport column are kept whole
        return "sport = %(sport)s", "(sport = %(sport)s OR sport IS NULL)", {"sport": sport}
    return "bytes_acked >= %(min_acked)s", "TRUE", {"min_acked": (max_acked or 0) // 1000}


def fetch_test_data(test: dict, bin_ns: int) -> dict:
    """All data for one test: {"iperf": {...}, "tcp": {...}, "cubic": {...}}.

    Probe times are seconds since the data connection's first probe sample.
    """
    with DB() as database:
        data = {"iperf": fetch_iperf(database, test)}
        tcp_where, cubic_where, params = data_connection_filters(database, test["id"])
        t0 = database.query(
            f"SELECT min(t_ns) FROM public.tcp_samples WHERE test_id = %(id)s AND {tcp_where}",
            {**params, "id": test["id"]},
        )[0][0]
        if t0 is None:
            t0 = database.query(
                f"SELECT min(t_ns) FROM public.cubic_samples WHERE test_id = %(id)s AND {cubic_where}",
                {**params, "id": test["id"]},
            )[0][0]
        if t0 is not None:
            data["tcp"] = fetch_tcp(database, test["id"], t0, bin_ns, tcp_where, params)
            data["cubic"] = fetch_cubic(database, test["id"], t0, bin_ns, cubic_where, params)
    return data


def sort_key(value: str):
    """Sort numbers numerically ("0.1" < "0.5" < "10"), everything else alphabetically."""
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


# --- Widgets -----------------------------------------------------------------

class MetricSidebar(ttk.Frame):
    """Scrollable list of checkboxes, one per metric, grouped by Metric.group."""

    def __init__(self, parent, on_change):
        super().__init__(parent, padding=(10, 10, 0, 10))
        self.vars: dict[str, tk.BooleanVar] = {}
        self.on_change = on_change

        buttons = ttk.Frame(self)
        buttons.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Label(buttons, text="Graphs", font="TkHeadingFont").pack(side="left")
        ttk.Button(buttons, text="None", width=5, command=lambda: self.set_all(False)).pack(side="right")
        ttk.Button(buttons, text="All", width=5, command=lambda: self.set_all(True)).pack(side="right")

        self.canvas = tk.Canvas(self, width=230, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        inner = ttk.Frame(self.canvas)
        inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=1, column=0, sticky="ns")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.rowconfigure(1, weight=1)

        frames: dict[str, ttk.LabelFrame] = {}
        for metric in METRICS:
            if metric.group not in frames:
                frames[metric.group] = ttk.LabelFrame(inner, text=metric.group, padding=4)
                frames[metric.group].pack(fill="x", pady=(0, 6))
            var = tk.BooleanVar(value=metric.default)
            self.vars[metric.key] = var
            ttk.Checkbutton(frames[metric.group], text=metric.label, variable=var,
                            command=self.on_change).pack(anchor="w")

        # Mouse wheel scrolls the list while the pointer is over it (Linux and Windows/macOS)
        self.canvas.bind("<Enter>", lambda e: self._bind_wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._bind_wheel(False))

    def _bind_wheel(self, active: bool) -> None:
        if active:
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
            self.canvas.bind_all("<MouseWheel>",
                                 lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        else:
            for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
                self.canvas.unbind_all(sequence)

    def set_all(self, value: bool) -> None:
        for var in self.vars.values():
            var.set(value)
        self.on_change()

    def selected(self) -> list[Metric]:
        return [metric for metric in METRICS if self.vars[metric.key].get()]


class FilterList(ttk.LabelFrame):
    """A small scrollable list of values with "(any)" at the top."""

    def __init__(self, parent, title, on_change, height=4):
        super().__init__(parent, text=title, padding=5)
        self.listbox = tk.Listbox(self, height=height, width=12, exportselection=False)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.listbox.bind("<<ListboxSelect>>", lambda event: on_change())

    def set_values(self, values) -> None:
        previous = self.get()
        items = [ANY] + sorted({str(v) for v in values}, key=sort_key)
        self.listbox.delete(0, "end")
        for item in items:
            self.listbox.insert("end", item)
        index = items.index(previous) if previous in items else 0
        self.listbox.selection_set(index)
        self.listbox.see(index)

    def get(self) -> str:
        selection = self.listbox.curselection()
        return self.listbox.get(selection[0]) if selection else ANY


class TestList(ttk.LabelFrame):
    """Scrollable test list with Ctrl/Shift and C/S selection shortcuts."""

    def __init__(self, parent, on_select):
        super().__init__(parent, text="Tests (Ctrl/Shift-click to compare)", padding=5)
        self.on_select = on_select
        self.names: list[str] = []
        self._c_held = False
        self._s_held = False

        self.search_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.search_var).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))

        self.listbox = tk.Listbox(self, height=12, width=38, selectmode="extended",
                                  exportselection=False, font="TkFixedFont")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        self.count_var = tk.StringVar()
        ttk.Label(self, textvariable=self.count_var).grid(row=2, column=0, columnspan=2, sticky="w")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.search_var.trace_add("write", lambda *_: self._refresh())
        self.listbox.bind("<<ListboxSelect>>", lambda event: self.on_select(self.get()))
        self.listbox.bind("<KeyPress-c>", self._set_c_held)
        self.listbox.bind("<KeyPress-C>", self._set_c_held)
        self.listbox.bind("<KeyRelease-c>", self._set_c_released)
        self.listbox.bind("<KeyRelease-C>", self._set_c_released)
        self.listbox.bind("<KeyPress-s>", self._set_s_held)
        self.listbox.bind("<KeyPress-S>", self._set_s_held)
        self.listbox.bind("<KeyRelease-s>", self._set_s_released)
        self.listbox.bind("<KeyRelease-S>", self._set_s_released)
        self.listbox.bind("<Button-1>", self._handle_alias_click)

    def _set_c_held(self, event):
        self._c_held = True
        return "break"

    def _set_c_released(self, event):
        self._c_held = False
        return "break"

    def _set_s_held(self, event):
        self._s_held = True
        return "break"

    def _set_s_released(self, event):
        self._s_held = False
        return "break"

    def _handle_alias_click(self, event):
        if not self._c_held and not self._s_held:
            return

        index = self.listbox.nearest(event.y)
        if self._s_held:
            anchor = self.listbox.index("anchor")
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(min(anchor, index), max(anchor, index))
        else:
            if self.listbox.selection_includes(index):
                self.listbox.selection_clear(index)
            else:
                self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.selection_anchor(index)
        self.on_select(self.get())
        return "break"

    def set_names(self, names) -> None:
        self.names = list(names)
        self._refresh()

    def get(self) -> list[str]:
        return [self.listbox.get(i) for i in self.listbox.curselection()]

    def _refresh(self) -> None:
        previous = self.get()
        text = self.search_var.get().lower()
        shown = [test_name for test_name in self.names if text in test_name.lower()]

        self.listbox.delete(0, "end")
        for test_name in shown:
            self.listbox.insert("end", test_name)
        self.count_var.set(f"{len(shown)} of {len(self.names)} tests shown")

        kept = [test_name for test_name in previous if test_name in shown]
        for test_name in kept:
            self.listbox.selection_set(shown.index(test_name))
        if kept:
            self.listbox.see(shown.index(kept[0]))
        if kept != previous:
            self.on_select(kept)  # some selected tests were filtered away


# --- Main window -------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    root.title("Test viewer")

    # Layout: [graph checkboxes] [plots] [filters/controls] [test list]
    figure = Figure(figsize=(8, 8), constrained_layout=True)
    canvas = FigureCanvasTkAgg(figure, master=root)
    canvas.get_tk_widget().grid(row=0, column=1, rowspan=3, sticky="nsew")

    controls = ttk.Frame(root, padding=10)
    controls.grid(row=0, column=2, rowspan=3, sticky="ns")

    root.columnconfigure(1, weight=1)
    root.rowconfigure(0, weight=1)

    tests: list[dict] = []
    tests_by_name: dict[str, dict] = {}
    data_cache: dict[tuple[str, int], dict] = {}
    param_filters: dict[str, FilterList] = {}
    details_var = tk.StringVar()
    line_plot_var = tk.BooleanVar(value=False)
    state = {"bin_ns": DEFAULT_BIN_MS * 1_000_000, "axes": []}

    def get_data(test_name: str) -> dict:
        key = (test_name, state["bin_ns"])
        if key not in data_cache:
            data_cache[key] = fetch_test_data(tests_by_name[test_name], state["bin_ns"])
        return data_cache[key]

    def plot_tests(test_names: list[str]) -> None:
        selected = sidebar.selected()
        figure.clear()

        if not selected:
            state["axes"] = []
            figure.text(0.5, 0.5, "Tick the graphs you want in the left sidebar",
                        ha="center", va="center")
            canvas.draw()
            return

        axes = list(figure.subplots(len(selected), 1, sharex=True, squeeze=False)[:, 0])
        state["axes"] = axes
        for axis in axes:
            axis.grid(True, alpha=0.3)

        missing_probe = []
        for test_name in test_names:
            test = tests_by_name[test_name]
            data = get_data(test_name)
            if "tcp" not in data:
                missing_probe.append(test_name)
            omit = max(0.0, parm_float(test, "omit", 0.0))
            label = f"{test['cca']} {test_name}"

            for axis, metric in zip(axes, selected):
                source = data.get(metric.source)
                if not source or not source["t"]:
                    continue
                points = [
                    (t, v) for t, v in zip(source["t"], metric.values(source)) if t >= omit
                ]
                if not points:
                    continue
                times, values = zip(*points)
                axis.plot(
                    times,
                    values,
                    linestyle="-" if line_plot_var.get() else "none",
                    marker=None if line_plot_var.get() else ".",
                    markersize=3,
                    label=label,
                )

        # X range: the user's min/max if given, otherwise all plotted data
        try:
            x_min = float(x_min_var.get()) if x_min_var.get().strip() else None
            x_max = float(x_max_var.get()) if x_max_var.get().strip() else None
        except ValueError:
            x_min = x_max = None
        all_x = [x for axis in axes for line in axis.lines for x in line.get_xdata()]
        data_min, data_max = (min(all_x), max(all_x)) if all_x else (0.0, 1.0)
        if data_min == data_max:
            data_min, data_max = data_min - 0.5, data_max + 0.5
        x_min = data_min if x_min is None else x_min
        x_max = data_max if x_max is None else x_max
        axes[0].set_xlim(x_min, x_max)

        # Y range per graph: fit the values inside the visible x range
        for axis in axes:
            visible_values = []
            for line in axis.lines:
                times, values = line.get_data()
                visible_values.extend(
                    value
                    for time, value in zip(times, values)
                    if x_min <= time <= x_max and math.isfinite(value)
                )
            if not visible_values:
                continue
            minimum = min(visible_values)
            maximum = max(visible_values)
            if minimum == maximum:
                padding = max(abs(minimum) * 0.05, 1.0)
            else:
                padding = (maximum - minimum) * 0.05
            axis.set_ylim(minimum - padding, maximum + padding)

        for axis, metric in zip(axes, selected):
            axis.set_ylabel(metric.label, fontsize="small")
            axis.tick_params(labelsize="small")
        axes[-1].set_xlabel("Time (s)")

        if test_names:
            if any(axis.lines for axis in axes):
                axes[0].legend(fontsize="small")
            axes[0].set_title(f"{len(test_names)} test(s) selected")
        else:
            axes[0].set_title("No test selected")

        # Details panel
        if len(test_names) == 1:
            test = tests_by_name[test_names[0]]
            parms_text = "\n".join(f"  {key}: {value}" for key, value in sorted(test["parms"].items()))
            probe_text = "no" if missing_probe else "yes"
            details_var.set(
                f"name: {test['name']}\ncca: {test['cca']}\nprobe data: {probe_text}\nparms:\n{parms_text}"
            )
        elif test_names:
            note = f"\nno probe data: {', '.join(missing_probe)}" if missing_probe else ""
            details_var.set(f"{len(test_names)} tests selected{note}")
        else:
            details_var.set("No test selected")

        canvas.draw()

    sidebar = MetricSidebar(root, lambda: plot_tests(test_list.get()))
    sidebar.grid(row=0, column=0, rowspan=3, sticky="ns")

    def matches(test: dict) -> bool:
        cca = cca_filter.get()
        if cca != ANY and test["cca"] != cca:
            return False
        for key, filter_list in param_filters.items():
            wanted = filter_list.get()
            if wanted != ANY and str(test["parms"].get(key)) != wanted:
                return False
        return True

    def apply_filters() -> None:
        test_list.set_names(test["name"] for test in tests if matches(test))

    cca_filter = FilterList(controls, "CCA", apply_filters)
    cca_filter.grid(row=0, column=0, sticky="ew")

    params_frame = ttk.LabelFrame(controls, text="Parameters", padding=5)
    params_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    test_list = TestList(root, plot_tests)
    test_list.grid(row=0, column=3, rowspan=2, sticky="nsew", padx=(0, 10), pady=10)
    controls.rowconfigure(2, weight=1)

    ttk.Label(root, textvariable=details_var, justify="left", font="TkFixedFont").grid(
        row=2, column=3, sticky="nw", padx=(0, 10), pady=(0, 10))

    def reload() -> None:
        nonlocal tests
        tests = fetch_tests()
        tests_by_name.clear()
        tests_by_name.update({test["name"]: test for test in tests})
        data_cache.clear()

        cca_filter.set_values(test["cca"] for test in tests)

        # One filter list per parameter key found in the table
        keys = sorted({key for test in tests for key in test["parms"]})
        for key in list(param_filters):
            if key not in keys:
                param_filters.pop(key).destroy()
        for i, key in enumerate(keys):
            if key not in param_filters:
                param_filters[key] = FilterList(params_frame, key, apply_filters, height=3)
            param_filters[key].grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
            param_filters[key].set_values(test["parms"][key] for test in tests if key in test["parms"])

        apply_filters()
        plot_tests(test_list.get())

    ttk.Button(controls, text="Reload from database", command=reload).grid(
        row=4, column=0, sticky="ew", pady=(10, 0))

    def delete_selected() -> None:
        names = test_list.get()
        if not names:
            messagebox.showwarning("No test selected", "Select a test to remove.")
            return

        names_text = "\n".join(f"- {name}" for name in names)
        if not messagebox.askyesno(
            "Remove test",
            f"Remove the following test(s) and their results?\n\n{names_text}",
        ):
            return

        try:
            with DB() as database:
                deleted = database.delete_tests_by_name(names)
        except psycopg.Error as error:
            messagebox.showerror("Remove test failed", str(error))
            return

        if deleted == 0:
            messagebox.showwarning("Test not found", "No matching test was found in the database.")
        else:
            reload()

    ttk.Button(controls, text="Remove selected test(s)", command=delete_selected).grid(
        row=5, column=0, sticky="ew", pady=(10, 0))

    ttk.Checkbutton(
        controls,
        text="Use line plots",
        variable=line_plot_var,
        command=lambda: plot_tests(test_list.get()),
    ).grid(row=6, column=0, sticky="w", pady=(10, 0))

    x_axis_frame = ttk.LabelFrame(controls, text="X-axis range (seconds)", padding=5)
    x_axis_frame.grid(row=7, column=0, sticky="ew", pady=(10, 0))
    x_min_var = tk.StringVar()
    x_max_var = tk.StringVar()
    ttk.Label(x_axis_frame, text="Min:").grid(row=0, column=0, sticky="w")
    ttk.Entry(x_axis_frame, textvariable=x_min_var, width=10).grid(row=0, column=1, padx=(5, 0))
    ttk.Label(x_axis_frame, text="Max:").grid(row=1, column=0, sticky="w")
    ttk.Entry(x_axis_frame, textvariable=x_max_var, width=10).grid(row=1, column=1, padx=(5, 0))

    def apply_x_axis_range() -> None:
        try:
            x_min = float(x_min_var.get()) if x_min_var.get().strip() else None
            x_max = float(x_max_var.get()) if x_max_var.get().strip() else None
        except ValueError:
            messagebox.showerror("Invalid X-axis range", "Minimum and maximum must be numbers.")
            return

        if x_min is not None and x_max is not None and x_min >= x_max:
            messagebox.showerror(
                "Invalid X-axis range",
                "The minimum must be smaller than the maximum.",
            )
            return

        plot_tests(test_list.get())

    ttk.Button(x_axis_frame, text="Apply", command=apply_x_axis_range).grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))

    # Probe samples are averaged into bins; smaller bins = more detail, slower loading
    bin_frame = ttk.LabelFrame(controls, text="Probe bin size (ms)", padding=5)
    bin_frame.grid(row=8, column=0, sticky="ew", pady=(10, 0))
    bin_var = tk.StringVar(value=str(DEFAULT_BIN_MS))
    ttk.Entry(bin_frame, textvariable=bin_var, width=10).grid(row=0, column=0)

    def apply_bin_size() -> None:
        try:
            bin_ms = float(bin_var.get())
            if bin_ms <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid bin size", "The bin size must be a positive number of milliseconds.")
            return
        state["bin_ns"] = max(1, int(bin_ms * 1_000_000))
        plot_tests(test_list.get())

    ttk.Button(bin_frame, text="Apply", command=apply_bin_size).grid(row=0, column=1, padx=(5, 0))

    def on_scroll(event) -> None:
        if event.inaxes is None or event.xdata is None:
            return
        factor = 0.8 if event.button == "up" else 1.25  # up = zoom in, down = zoom out
        left, right = event.inaxes.get_xlim()
        center = event.xdata  # zoom around the mouse position
        event.inaxes.set_xlim(center - (center - left) * factor,
                              center + (right - center) * factor)
        canvas.draw_idle()

    canvas.mpl_connect("scroll_event", on_scroll)

    pan_state = {"axis": None, "start_x": None, "start_xlim": None}

    def on_press(event) -> None:
        if event.button != 1 or event.inaxes is None:  # 1 = left mouse button
            return
        pan_state["axis"] = event.inaxes
        pan_state["start_x"] = event.x  # pixel position, not data position
        pan_state["start_xlim"] = event.inaxes.get_xlim()

    def on_motion(event) -> None:
        axis = pan_state["axis"]
        if axis is None:
            return
        left, right = pan_state["start_xlim"]
        data_per_pixel = (right - left) / axis.bbox.width
        shift = (event.x - pan_state["start_x"]) * data_per_pixel
        axis.set_xlim(left - shift, right - shift)
        canvas.draw_idle()

    def on_release(event) -> None:
        pan_state["axis"] = None

    canvas.mpl_connect("button_press_event", on_press)
    canvas.mpl_connect("motion_notify_event", on_motion)
    canvas.mpl_connect("button_release_event", on_release)

    def close() -> None:
        figure.clear()
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    reload()
    root.mainloop()


if __name__ == "__main__":
    main()