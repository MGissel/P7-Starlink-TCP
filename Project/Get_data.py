import csv
import json
import math
import tkinter as tk
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import matplotlib
import numpy as np

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
    "wmem_queued", "sndbuf", "rto_j", "reordering", "rack_rtt_us",
]
TCP_MAX = ["ca_state", "backoff"]  # states: worst value in the bin
TCP_MIN = ["minrtt_us", "rack_rtt_us"]   # lowest value in the bin
TCP_COUNTERS = [                   # cumulative: first/last value in the bin -> deltas
    "bytes_acked", "bytes_retrans", "total_retrans", "lost", "delivered",
    "delivered_ce", "busy_j", "rwnd_lim_j", "sndbuf_lim_j",
]
CUBIC_COLUMNS = ["w_max", "k", "epoch_start", "cnt", "delay_min"]
IPERF_COLUMNS = ["throughput", "rtt_ms", "cwnd", "retrans"]
IRTT_AGGREGATES = [   # (name, SQL aggregate over the bin)
    ("avg_rtt", "avg(rtt_ns)"),
    ("min_rtt", "min(rtt_ns)"),
    ("max_rtt", "max(rtt_ns)"),
    ("sd_rtt", "stddev_samp(rtt_ns)"),
    ("avg_send", "avg(send_delay_ns)"),
    ("avg_receive", "avg(receive_delay_ns)"),
    ("packets", "count(*)"),
    ("lost", "count(*) FILTER (WHERE lost > 0)"),
    ("lost_out", "count(*) FILTER (WHERE lost = 1)"),
    ("lost_back", "count(*) FILTER (WHERE lost = 2)"),
]


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
    Metric("rack_rtt", "TCP state", "Latest RTT sample (ms)", "tcp", col("avg_rack_rtt_us", 1e-3)),
    Metric("rack_rtt_min", "TCP state", "Latest RTT sample, min in bin (ms)", "tcp", col("min_rack_rtt_us", 1e-3)),
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

    # irtt: small UDP packets at a fixed interval, through the same link (sanity check for RTT)
    Metric("irtt_rtt", "irtt", "irtt RTT (ms)", "irtt", col("avg_rtt", 1e-6)),
    Metric("irtt_rtt_min", "irtt", "irtt min RTT (ms)", "irtt", col("min_rtt", 1e-6)),
    Metric("irtt_rtt_max", "irtt", "irtt max RTT (ms)", "irtt", col("max_rtt", 1e-6)),
    Metric("irtt_jitter", "irtt", "irtt RTT std dev (ms)", "irtt", col("sd_rtt", 1e-6)),
    Metric("irtt_send", "irtt", "irtt one-way delay out (ms)", "irtt", col("avg_send", 1e-6)),
    Metric("irtt_receive", "irtt", "irtt one-way delay back (ms)", "irtt", col("avg_receive", 1e-6)),
    Metric("irtt_loss", "irtt", "irtt loss (%)", "irtt", lambda d: ratio(d["lost"], d["packets"])),
    Metric("irtt_loss_out", "irtt", "irtt loss out (%)", "irtt", lambda d: ratio(d["lost_out"], d["packets"])),
    Metric("irtt_loss_back", "irtt", "irtt loss back (%)", "irtt", lambda d: ratio(d["lost_back"], d["packets"])),

    # The iperf3 interval results (the old graphs)
    Metric("iperf_throughput", "iperf3 (per interval)", "iperf throughput (Mbit/s)", "iperf", col("throughput", 1e-6)),
    Metric("iperf_rtt", "iperf3 (per interval)", "iperf RTT (ms)", "iperf", col("rtt_ms")),
    Metric("iperf_cwnd", "iperf3 (per interval)", "iperf cwnd (KB)", "iperf", col("cwnd", KB)),
    Metric("iperf_retrans", "iperf3 (per interval)", "iperf retransmits", "iperf", col("retrans")),
]


# --- Data access -------------------------------------------------------------

_database = None


def get_db() -> DB:
    """One connection for the whole viewer; reconnects if it was lost (e.g. Tailscale dropped)."""
    global _database
    if _database is None or _database.conn.closed or _database.conn.broken:
        _database = DB()
    return _database


def run_query(sql_text, params=None):
    """Query with one automatic retry on a lost connection."""
    global _database
    try:
        return get_db().query(sql_text, params)
    except psycopg.OperationalError:
        _database = None
        return get_db().query(sql_text, params)

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
    rows = list(run_query("SELECT id, name, cca, parms FROM public.tests") or [])

    tests = []
    for test_id, test_name, cca, parms in rows:
        if isinstance(parms, str):  # json stored as text; jsonb usually arrives as a dict already
            parms = json.loads(parms)
        tests.append({"id": test_id, "name": test_name, "cca": cca, "parms": parms or {}})
    return tests


def fetch_iperf(test: dict) -> dict:
    rows = run_query(
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


def fetch_tcp(test_id, t0: int, bin_ns: int, where: str, params: dict) -> dict:
    names, select = ["bin"], ["(t_ns - %(t0)s) / %(bin)s"]
    for c in TCP_AVG:
        names.append(f"avg_{c}"); select.append(f"avg({c})")
    for c in TCP_MAX:
        names.append(f"max_{c}"); select.append(f"max({c})")
    for c in TCP_MIN:
        names.append(f"min_{c}"); select.append(f"min({c})")
    for c in TCP_COUNTERS:
        names += [f"first_{c}", f"last_{c}"]; select += [f"min({c})", f"max({c})"]

    rows = run_query(
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


def fetch_cubic(test_id, t0: int, bin_ns: int, where: str, params: dict) -> dict:
    names = ["bin"] + [f"max_{c}" for c in CUBIC_COLUMNS]
    select = ["(t_ns - %(t0)s) / %(bin)s"] + [f"max({c})" for c in CUBIC_COLUMNS]
    rows = run_query(
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


def fetch_irtt(test_id, t0: int, bin_ns: int) -> dict:
    names = ["bin"] + [name for name, _ in IRTT_AGGREGATES]
    # floor(), not integer division: irtt starts before the probe, so times can be negative
    select = ["floor((t_ns - %(t0)s)::float8 / %(bin)s)::bigint"] + [agg for _, agg in IRTT_AGGREGATES]
    rows = run_query(
        f"""
        SELECT {', '.join(select)}
        FROM public.irtt_samples
        WHERE test_id = %(id)s
        GROUP BY 1
        ORDER BY 1
        """,
        {"id": test_id, "t0": t0, "bin": bin_ns},
    ) or []
    data = to_columns(rows, names)
    add_bin_times(data, bin_ns)
    return data


def data_connection_filters(test_id) -> tuple[str, str, dict]:
    """SQL conditions that keep only the iperf3 data connection.

    The probe also sees iperf3's control connection (same server port).
    Mixing the two breaks the counters, e.g. a hugely negative goodput.
    - Logs with a sport column: the socket that ACKed the most bytes. Looking at the
      last 20 000 samples is enough and fast (it uses the time index instead of
      reading the whole test).
    - Older logs without sport: drop samples whose bytes_acked is below
      0.1 % of the maximum (the control connection only sends a few KB).
    Returns (tcp_where, cubic_where, params).
    """
    rows = run_query(
        """
        SELECT sport, max(bytes_acked) FROM (
            SELECT sport, bytes_acked FROM public.tcp_samples
            WHERE test_id = %(id)s
            ORDER BY t_ns DESC LIMIT 20000
        ) recent
        GROUP BY sport
        ORDER BY 2 DESC NULLS LAST
        LIMIT 1
        """,
        {"id": test_id},
    )
    sport = rows[0][0] if rows else None
    if sport is not None:
        # CUBIC logs without a sport column are kept whole
        return "sport = %(sport)s", "(sport = %(sport)s OR sport IS NULL)", {"sport": sport}
    max_acked = run_query(
        "SELECT max(bytes_acked) FROM public.tcp_samples WHERE test_id = %s", (test_id,)
    )[0][0]
    return "bytes_acked >= %(min_acked)s", "TRUE", {"min_acked": (max_acked or 0) // 1000}


def fetch_context(test: dict) -> dict:
    """Per test, independent of bin size: which connection to use and where time 0 is.

    Probe times are seconds since the data connection's first probe sample.
    t0 is None when the test has no probe or irtt data.
    """
    tcp_where, cubic_where, params = data_connection_filters(test["id"])
    t0 = run_query(
        f"SELECT min(t_ns) FROM public.tcp_samples WHERE test_id = %(id)s AND {tcp_where}",
        {**params, "id": test["id"]},
    )[0][0]
    if t0 is None:
        t0 = run_query(
            f"SELECT min(t_ns) FROM public.cubic_samples WHERE test_id = %(id)s AND {cubic_where}",
            {**params, "id": test["id"]},
        )[0][0]
    if t0 is None:
        t0 = run_query(
            "SELECT min(t_ns) FROM public.irtt_samples WHERE test_id = %s", (test["id"],)
        )[0][0]
    return {"t0": t0, "tcp_where": tcp_where, "cubic_where": cubic_where, "params": params}


def fetch_source(test: dict, context: dict, source: str, bin_ns: int) -> dict | None:
    """One data source ("iperf", "tcp", "cubic" or "irtt") for one test."""
    if source == "iperf":
        return fetch_iperf(test)
    t0 = context["t0"]
    if t0 is None:
        return None
    if source == "tcp":
        return fetch_tcp(test["id"], t0, bin_ns, context["tcp_where"], context["params"])
    if source == "cubic":
        return fetch_cubic(test["id"], t0, bin_ns, context["cubic_where"], context["params"])
    if source == "irtt":
        return fetch_irtt(test["id"], t0, bin_ns)
    return None


METRIC_BY_KEY = {metric.key: metric for metric in METRICS}


# --- CCA comparison ----------------------------------------------------------

COMPARE_DEFAULT_BIN_MS = 1000    # one goodput/RTT sample per second for the statistics
COMPARE_DEFAULT_SPAN_S = 120     # length of the time-series window if no range is given
PAPER_WIDTH_IN = 3.5             # one IEEE column
PAPER_RC = {                     # font sizes for the saved figures
    "font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7,
    "xtick.labelsize": 7, "ytick.labelsize": 7,
}
LINE_STYLES = ["-", "--", "-.", ":"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]


@dataclass
class RunSummary:
    """One test reduced to equally spaced samples, ready to compare with other tests."""
    label: str
    source: str               # "probe" or "iperf" (iperf: sender side, no retransmission overhead)
    t: list[float]
    goodput: list[float]      # Mbit/s
    rtt: list[float]          # ms
    cwnd: list[float]         # segments (probe) or KB (iperf)
    retrans: list[float]      # retransmission overhead per sample (%), NaN if unknown
    total_retrans_pct: float  # retransmitted bytes / all sent bytes over the whole test (%)


def finite(values) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    return array[np.isfinite(array)]


def percentile(values, q: float) -> float:
    array = finite(values)
    return float(np.percentile(array, q)) if array.size else math.nan


def run_labels(tests: list[dict]) -> list[str]:
    """The CCA name, plus the test name when the same CCA is selected more than once."""
    counts = Counter(test["cca"] for test in tests)
    return [test["cca"] if counts[test["cca"]] == 1 else f"{test['cca']} ({test['name']})"
            for test in tests]


def summarize_run(label: str, test: dict, tcp: dict | None, iperf: dict | None) -> RunSummary | None:
    """Prefer the probe data (receiver-acknowledged bytes); fall back to iperf3 intervals."""
    omit = max(0.0, parm_float(test, "omit", 0.0))
    if tcp and tcp["t"]:
        source, t = "probe", tcp["t"]
        goodput = METRIC_BY_KEY["goodput"].values(tcp)
        rtt = METRIC_BY_KEY["srtt"].values(tcp)
        cwnd = tcp["avg_cwnd"]
        retrans = METRIC_BY_KEY["retrans_overhead"].values(tcp)
    elif iperf and iperf["t"]:
        source, t = "iperf", iperf["t"]
        goodput = [v * 1e-6 for v in iperf["throughput"]]
        rtt = iperf["rtt_ms"]
        cwnd = [v * KB for v in iperf["cwnd"]]
        retrans = [math.nan] * len(t)
    else:
        return None

    keep = [i for i, time in enumerate(t) if time >= omit]
    if not keep:
        return None

    def pick(seq):
        return [seq[i] for i in keep]

    total_pct = math.nan
    if source == "probe":
        acked = sum(v for v in pick(tcp["d_bytes_acked"]) if math.isfinite(v))
        resent = sum(v for v in pick(tcp["d_bytes_retrans"]) if math.isfinite(v))
        total_pct = resent / (acked + resent) * 100 if acked + resent else math.nan

    return RunSummary(label, source, pick(t), pick(goodput), pick(rtt), pick(cwnd),
                      pick(retrans), total_pct)


def run_styles(runs: list[RunSummary]) -> dict[str, dict]:
    """The same colour, line style and marker for a CCA in every figure (readable in greyscale too)."""
    colors = matplotlib.colormaps["tab10"].colors
    return {
        run.label: {"color": colors[i % len(colors)],
                    "linestyle": LINE_STYLES[i % len(LINE_STYLES)],
                    "marker": MARKERS[i % len(MARKERS)]}
        for i, run in enumerate(runs)
    }


def fit_y_to_visible(axis, x_min: float, x_max: float) -> None:
    values = []
    for line in axis.lines:
        xs, ys = line.get_data()
        values.extend(y for x, y in zip(xs, ys) if x_min <= x <= x_max and math.isfinite(y))
    if values:
        low, high = min(values), max(values)
        pad = (high - low) * 0.05 if high > low else max(abs(low) * 0.05, 1.0)
        axis.set_ylim(0.0 if low >= 0 else low - pad, high + pad)


def draw_timeseries(fig, runs, styles, options) -> None:
    """Goodput and cwnd over time, with dashed lines at the handovers."""
    ax_goodput, ax_cwnd = fig.subplots(2, 1, sharex=True)
    x_min, x_max = options["x_range"]
    for run in runs:
        style = styles[run.label]
        points = [(t, g, c) for t, g, c in zip(run.t, run.goodput, run.cwnd) if x_min <= t <= x_max]
        if not points:
            continue
        t, goodput, cwnd = zip(*points)
        line = {"color": style["color"], "linestyle": style["linestyle"], "linewidth": 1}
        ax_goodput.plot(t, goodput, label=run.label, **line)
        ax_cwnd.plot(t, cwnd, **line)

    period, offset = options["handover"]
    if period:
        first = offset + math.ceil((x_min - offset) / period) * period
        for x in np.arange(first, x_max, period):
            for axis in (ax_goodput, ax_cwnd):
                axis.axvline(x, color="grey", linestyle=":", linewidth=0.8, zorder=0)

    sources = {run.source for run in runs}
    cwnd_unit = {frozenset({"probe"}): "segments", frozenset({"iperf"}): "KB"}.get(
        frozenset(sources), "segments / KB")
    ax_goodput.set_ylabel("Goodput (Mbit/s)")
    ax_cwnd.set_ylabel(f"cwnd ({cwnd_unit})")
    ax_cwnd.set_xlabel("Time (s)")
    ax_goodput.set_xlim(x_min, x_max)
    for axis in (ax_goodput, ax_cwnd):
        axis.grid(True, alpha=0.3)
        fit_y_to_visible(axis, x_min, x_max)
    if ax_goodput.lines:   # above the plot, so it never hides the dips
        ax_goodput.legend(loc="lower left", bbox_to_anchor=(0, 1.02, 1, 0.2), mode="expand",
                          ncol=min(len(ax_goodput.lines), 3), frameon=False, borderaxespad=0)


def draw_cdf(fig, runs, styles, options) -> None:
    """Distribution of goodput over the whole test: further right is better."""
    axis = fig.subplots()
    for run in runs:
        values = np.sort(finite(run.goodput))
        if not values.size:
            continue
        style = styles[run.label]
        axis.step(values, np.arange(1, values.size + 1) / values.size, where="post",
                  label=run.label, color=style["color"], linestyle=style["linestyle"], linewidth=1)
    axis.set_xlabel("Goodput (Mbit/s)")
    axis.set_ylabel("CDF")
    axis.set_ylim(0, 1.0)
    axis.grid(True, alpha=0.3)
    if axis.lines:
        axis.legend(loc="upper left")


def draw_tradeoff(fig, runs, styles, options) -> None:
    """Median goodput against median RTT, bars from the 10th to the 90th percentile: up-left is better."""
    axis = fig.subplots()
    for run in runs:
        x, y = percentile(run.rtt, 50), percentile(run.goodput, 50)
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        xerr = [[x - percentile(run.rtt, 10)], [percentile(run.rtt, 90) - x]]
        yerr = [[y - percentile(run.goodput, 10)], [percentile(run.goodput, 90) - y]]
        style = styles[run.label]
        axis.errorbar(x, y, xerr=xerr, yerr=yerr, fmt=style["marker"], color=style["color"],
                      capsize=3, markersize=5, elinewidth=0.8, label=run.label)
    axis.set_xlabel("Median RTT (ms)")
    axis.set_ylabel("Median goodput (Mbit/s)")
    axis.grid(True, alpha=0.3)
    if runs:
        axis.legend(loc="best")


def draw_retrans(fig, runs, styles, options) -> None:
    """Retransmission overhead per sample as box plots (probe data only)."""
    axis = fig.subplots()
    kept = [(run, finite(run.retrans)) for run in runs]
    kept = [(run, values) for run, values in kept if values.size]
    if not kept:
        axis.text(0.5, 0.5, "No retransmission data\n(needs probe data)",
                  ha="center", va="center", transform=axis.transAxes)
        axis.set_axis_off()
        return
    boxes = axis.boxplot([values for _, values in kept], showfliers=False, patch_artist=True,
                         medianprops={"color": "black"})
    for box, (run, _) in zip(boxes["boxes"], kept):
        box.set_facecolor(styles[run.label]["color"])
        box.set_alpha(0.6)
    labels = [run.label for run, _ in kept]
    axis.set_xticks(range(1, len(kept) + 1), labels,
                    rotation=20 if max(len(label) for label in labels) > 8 else 0,
                    ha="right" if max(len(label) for label in labels) > 8 else "center")
    axis.set_ylabel("Retransmission overhead (%)")
    axis.grid(True, axis="y", alpha=0.3)


# (file name, tab title, draw function, height of the saved figure in inches)
COMPARE_PLOTS = [
    ("goodput_timeseries", "Goodput over time", draw_timeseries, 3.4),
    ("goodput_cdf", "Goodput CDF", draw_cdf, 2.4),
    ("goodput_vs_rtt", "Goodput vs RTT", draw_tradeoff, 2.4),
    ("retrans_overhead", "Retransmissions", draw_retrans, 2.4),
]

SUMMARY_COLUMNS = [
    "CCA", "Data",
    "Goodput median (Mbit/s)", "Goodput p10 (Mbit/s)", "Goodput p90 (Mbit/s)",
    "RTT median (ms)", "RTT p10 (ms)", "RTT p90 (ms)",
    "Retrans. overhead (%)", "Samples",
]


def summary_rows(runs: list[RunSummary]) -> list[list]:
    rows = []
    for run in runs:
        rows.append([
            run.label, run.source,
            percentile(run.goodput, 50), percentile(run.goodput, 10), percentile(run.goodput, 90),
            percentile(run.rtt, 50), percentile(run.rtt, 10), percentile(run.rtt, 90),
            run.total_retrans_pct, len(finite(run.goodput)),
        ])
    return rows


def format_cell(value, digits: int = 2) -> str:
    if isinstance(value, float):
        return "--" if not math.isfinite(value) else f"{value:.{digits}f}"
    return str(value)


def latex_escape(text: str) -> str:
    for char, escaped in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"),
                          ("&", r"\&"), ("#", r"\#"), ("$", r"\$")):
        text = text.replace(char, escaped)
    return text


def summary_latex(runs: list[RunSummary], bin_ms: float) -> str:
    """A booktabs table: median with the 10th-90th percentile for goodput and RTT."""
    lines = [
        r"% Needs \usepackage{booktabs}",
        r"\begin{table}[t]",
        r"\centering",
        rf"\caption{{Comparison of CCAs. Medians with 10th and 90th percentile, "
        rf"over {bin_ms:g}\,ms samples.}}",
        r"\label{tab:cca-comparison}",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        r" & \multicolumn{3}{c}{Goodput (Mbit/s)} & \multicolumn{3}{c}{RTT (ms)} & Retrans. \\",
        r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}",
        r"CCA & Median & P10 & P90 & Median & P10 & P90 & (\%) \\",
        r"\midrule",
    ]
    for row in summary_rows(runs):
        label = latex_escape(row[0]) + (r"$^\dagger$" if row[1] == "iperf" else "")
        cells = [format_cell(v, 1) for v in row[2:8]] + [format_cell(row[8], 2)]
        lines.append(" & ".join([label] + cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    if any(run.source == "iperf" for run in runs):
        lines.append(r"\\[2pt]{\footnotesize $^\dagger$ iperf3 sender-side data, no probe data.}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


class CompareWindow(tk.Toplevel):
    """Comparison plots for the selected tests, with saving for the paper."""

    def __init__(self, master, test_names: list[str],
                 load_runs: Callable[[int], tuple[list[RunSummary], list[str]]],
                 x_range: tuple[float | None, float | None]):
        super().__init__(master)
        self.title(f"Compare {len(test_names)} test(s)")
        self.geometry("950x720")
        self.load_runs = load_runs
        self.runs: list[RunSummary] = []
        self.bin_ms = float(COMPARE_DEFAULT_BIN_MS)

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        self.bin_var = tk.StringVar(value=str(COMPARE_DEFAULT_BIN_MS))
        self.x_min_var = tk.StringVar(value="" if x_range[0] is None else f"{x_range[0]:g}")
        self.x_max_var = tk.StringVar(value="" if x_range[1] is None else f"{x_range[1]:g}")
        self.period_var = tk.StringVar(value="15")
        self.offset_var = tk.StringVar(value="0")
        self.prefix_var = tk.StringVar(value="compare")
        fields = [
            ("Sample interval (ms)", self.bin_var),
            ("Time from (s)", self.x_min_var),
            ("to (s)", self.x_max_var),
            ("Handover every (s)", self.period_var),
            ("offset (s)", self.offset_var),
            ("File prefix", self.prefix_var),
        ]
        for column, (text, var) in enumerate(fields):
            ttk.Label(bar, text=text).grid(row=0, column=column, sticky="w", padx=(0, 6))
            ttk.Entry(bar, textvariable=var, width=10).grid(row=1, column=column, sticky="w", padx=(0, 6))
        ttk.Button(bar, text="Update", command=self.update_plots).grid(row=1, column=len(fields), padx=(6, 0))
        ttk.Button(bar, text="Save…", command=self.save).grid(row=1, column=len(fields) + 1, padx=(6, 0))

        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var, padding=(8, 0)).pack(fill="x")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvases = []
        for _, title, _, _ in COMPARE_PLOTS:
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=title)
            figure = Figure(figsize=(7, 5), constrained_layout=True)
            canvas = FigureCanvasTkAgg(figure, master=frame)
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self.canvases.append((figure, canvas))

        table_frame = ttk.Frame(notebook)
        notebook.add(table_frame, text="Table")
        headings = SUMMARY_COLUMNS
        self.table = ttk.Treeview(table_frame, columns=headings, show="headings")
        for name in headings:
            self.table.heading(name, text=name)
            self.table.column(name, width=95, anchor="e" if name not in ("CCA", "Data") else "w")
        self.table.pack(fill="both", expand=True)

        self.update_plots()

    def _read_fields(self) -> dict | None:
        def number(var, default=None):
            text = var.get().strip()
            return default if not text else float(text)
        try:
            bin_ms = number(self.bin_var, float(COMPARE_DEFAULT_BIN_MS))
            x_min, x_max = number(self.x_min_var), number(self.x_max_var)
            period, offset = number(self.period_var, 0.0), number(self.offset_var, 0.0)
        except ValueError:
            messagebox.showerror("Invalid value", "All fields must be numbers (or empty).", parent=self)
            return None
        if bin_ms <= 0 or period < 0:
            messagebox.showerror("Invalid value", "Sample interval must be positive, handover period ≥ 0.",
                                 parent=self)
            return None
        return {"bin_ms": bin_ms, "x_min": x_min, "x_max": x_max, "period": period, "offset": offset}

    def _plot_options(self, values: dict) -> dict:
        starts = [run.t[0] for run in self.runs if run.t]
        x_min = values["x_min"] if values["x_min"] is not None else (min(starts) if starts else 0.0)
        x_max = values["x_max"] if values["x_max"] is not None else x_min + COMPARE_DEFAULT_SPAN_S
        if x_max <= x_min:
            x_max = x_min + 1.0
        return {"x_range": (x_min, x_max), "handover": (values["period"], values["offset"])}

    def update_plots(self) -> None:
        values = self._read_fields()
        if values is None:
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.runs, skipped = self.load_runs(max(1, int(values["bin_ms"] * 1_000_000)))
        except psycopg.Error as error:
            messagebox.showerror("Loading failed", str(error), parent=self)
            return
        finally:
            self.config(cursor="")
        self.bin_ms = values["bin_ms"]

        notes = []
        if skipped:
            notes.append(f"no data: {', '.join(skipped)}")
        iperf_only = [run.label for run in self.runs if run.source == "iperf"]
        if iperf_only:
            notes.append(f"iperf3 sender data only (no probe): {', '.join(iperf_only)}")
        self.status_var.set("; ".join(notes))

        styles = run_styles(self.runs)
        options = self._plot_options(values)
        for (figure, canvas), (_, _, draw, _) in zip(self.canvases, COMPARE_PLOTS):
            figure.clear()
            if self.runs:
                draw(figure, self.runs, styles, options)
            else:
                figure.text(0.5, 0.5, "No data for the selected tests", ha="center", va="center")
            canvas.draw()

        self.table.delete(*self.table.get_children())
        for row in summary_rows(self.runs):
            self.table.insert("", "end", values=[format_cell(v) for v in row])

    def save(self) -> None:
        if not self.runs:
            messagebox.showwarning("Nothing to save", "There is no data to save.", parent=self)
            return
        values = self._read_fields()
        if values is None:
            return
        folder = filedialog.askdirectory(parent=self, title="Folder for the comparison figures")
        if not folder:
            return
        folder = Path(folder)
        prefix = self.prefix_var.get().strip() or "compare"
        styles = run_styles(self.runs)
        options = self._plot_options(values)

        saved = []
        try:
            with matplotlib.rc_context(PAPER_RC):
                for name, _, draw, height in COMPARE_PLOTS:
                    figure = Figure(figsize=(PAPER_WIDTH_IN, height), constrained_layout=True)
                    draw(figure, self.runs, styles, options)
                    for extension in ("pdf", "png"):
                        path = folder / f"{prefix}_{name}.{extension}"
                        figure.savefig(path, dpi=300)
                        saved.append(path.name)

            csv_path = folder / f"{prefix}_summary.csv"
            with open(csv_path, "w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(SUMMARY_COLUMNS)
                for row in summary_rows(self.runs):
                    writer.writerow([format_cell(v, 3) for v in row])
            saved.append(csv_path.name)

            tex_path = folder / f"{prefix}_summary.tex"
            tex_path.write_text(summary_latex(self.runs, self.bin_ms))
            saved.append(tex_path.name)
        except OSError as error:
            messagebox.showerror("Saving failed", str(error), parent=self)
            return

        messagebox.showinfo("Saved", f"Saved to {folder}:\n\n" + "\n".join(saved), parent=self)


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
    context_cache: dict[str, dict] = {}                     # test -> connection filter and t0
    source_cache: dict[tuple[str, str, int], dict | None] = {}   # (test, source, bin) -> data
    param_filters: dict[str, FilterList] = {}
    details_var = tk.StringVar()
    line_plot_var = tk.BooleanVar(value=False)
    state = {"bin_ns": DEFAULT_BIN_MS * 1_000_000, "axes": []}

    def get_context(test_name: str) -> dict:
        if test_name not in context_cache:
            context_cache[test_name] = fetch_context(tests_by_name[test_name])
        return context_cache[test_name]

    def get_source(test_name: str, source: str, bin_ns: int) -> dict | None:
        """One source of one test, loaded once per bin size (iperf3 data isn't binned)."""
        key = (test_name, source, 0 if source == "iperf" else bin_ns)
        if key not in source_cache:
            context = get_context(test_name) if source != "iperf" else {}
            source_cache[key] = fetch_source(tests_by_name[test_name], context, source, bin_ns)
        return source_cache[key]

    def get_data(test_name: str, sources: set[str]) -> dict:
        """Only the sources the ticked graphs need."""
        return {source: get_source(test_name, source, state["bin_ns"]) for source in sources}

    def load_runs(test_names: list[str], bin_ns: int) -> tuple[list[RunSummary], list[str]]:
        """The selected tests as RunSummary objects; names of tests without any data are returned too."""
        selected = [tests_by_name[name] for name in test_names if name in tests_by_name]
        runs, skipped = [], []
        for label, test in zip(run_labels(selected), selected):
            tcp = get_source(test["name"], "tcp", bin_ns)
            iperf = None if tcp and tcp["t"] else get_source(test["name"], "iperf", bin_ns)
            run = summarize_run(label, test, tcp, iperf)
            if run is None:
                skipped.append(test["name"])
            else:
                runs.append(run)
        return runs, skipped

    def open_compare() -> None:
        names = test_list.get()
        if not names:
            messagebox.showwarning("No test selected",
                                   "Select the tests to compare (Ctrl/Shift-click for several).")
            return
        try:
            x_range = (float(x_min_var.get()) if x_min_var.get().strip() else None,
                       float(x_max_var.get()) if x_max_var.get().strip() else None)
        except ValueError:
            x_range = (None, None)
        CompareWindow(root, names, lambda bin_ns: load_runs(names, bin_ns), x_range)

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

        needed = {metric.source for metric in selected}
        missing_probe = []
        for test_name in test_names:
            test = tests_by_name[test_name]
            data = get_data(test_name, needed)
            if get_context(test_name)["t0"] is None:
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
        context_cache.clear()
        source_cache.clear()

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

    ttk.Button(controls, text="Compare selected tests…", command=lambda: open_compare()).grid(
        row=3, column=0, sticky="ew", pady=(10, 0))

    ttk.Button(controls, text="Reload from database", command=reload).grid(
        row=4, column=0, sticky="ew", pady=(10, 0))
    root.bind("<F5>", lambda event: reload())
    root.bind("<Control-r>", lambda event: reload())

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
            deleted = get_db().delete_tests_by_name(names)
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
        if _database is not None:
            _database.close()
        figure.clear()
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    reload()
    root.mainloop()


if __name__ == "__main__":
    main()