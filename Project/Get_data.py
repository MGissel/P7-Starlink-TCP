import json
import math
import random
import tkinter as tk
from tkinter import ttk

import matplotlib

matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

try:
    from DB import DB
except ImportError as error:
    print(f"Could not import DB: {error!r}, using sample data")
    DB = None

RESULTS_TABLE = "results"  # <-- change this to the real name of your results table

ANY = "(any)"

# (column, axis label, scale factor applied before plotting)
METRICS = [
    ("throughput", "Throughput (Gbit/s)", 1e-9),  # assumes throughput is stored in bit/s
    ("rtt_ms", "RTT (ms)", 1),
    ("cwnd", "cwnd", 1),
    ("retrans", "Retransmits", 1),
]


# --- Sample data (used only when DB can't be imported) -----------------------

SAMPLE_TESTS = [
    ("d0ddee23-1855-4b63-95e9-5799995e3e70", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "5", "interval": "0.5"}'),
    ("eea24003-f153-4090-b8bb-88bf19a44ffb", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "5", "interval": "0.5"}'),
    ("f32d247d-3b8d-4649-8961-ba9b491d598a", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "5", "interval": "0.5"}'),
    ("6eae8c48-436b-44fb-8f7c-4acff415b555", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "5", "interval": "0.1"}'),
    ("de7ffac0-58c1-462e-be6b-097fe1350f5d", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "5", "interval": "0.2"}'),
    ("b1f86817-adc3-4164-bf17-4baf78639446", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "3", "interval": "0.2"}'),
    ("59d538d6-4d50-4718-81d2-7d244996f606", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "3", "interval": "0.1"}'),
    ("c4e6e4f8-c83a-41ce-8230-7fa617abe967", "BBR", '{"host": "localhost", "json": "true", "logfile": "output.log", "duration": "3", "interval": "0.5"}'),
]

# (throughput, rtt_ms, cwnd, retrans) rows, ordered by id
SAMPLE_RESULTS = {
    "d0ddee23-1855-4b63-95e9-5799995e3e70": [
        (28034988999.02825, 35, 1506109, 0), (34695652330.966484, 48, 1571592, 0),
        (37991807300.82697, 43, 1571592, 0), (35160723277.87576, 33, 1571592, 0),
        (38006228095.75957, 33, 1571592, 0), (37905868763.1227, 32, 1571592, 0),
        (37335821820.2281, 32, 1571592, 0), (38444683405.452484, 35, 1571592, 0),
        (38191652240.89948, 42, 1571592, 0), (38381376639.609, 37, 1571592, 0),
    ],
    "eea24003-f153-4090-b8bb-88bf19a44ffb": [
        (34648832988.71082, 67, 1047728, 0), (36977600103.32497, 41, 1047728, 0),
        (37585234312.65436, 33, 1047728, 0), (37901751285.90566, 39, 1047728, 0),
        (36058498634.78027, 38, 1047728, 0), (37622382142.31877, 41, 1047728, 0),
        (37520222468.9041, 31, 1047728, 0), (38132437538.4066, 31, 1047728, 0),
        (38027580150.90617, 37, 1047728, 0), (37862075856.047775, 31, 1047728, 0),
    ],
    "f32d247d-3b8d-4649-8961-ba9b491d598a": [
        (29265754143.23437, 34, 1309660, 0), (32933897480.836678, 39, 1309660, 0),
        (38024484375.77637, 32, 1309660, 0), (37813522325.8434, 33, 1309660, 0),
        (38236056947.95499, 40, 1309660, 0), (37052096093.06734, 47, 1309660, 0),
        (37259650972.651344, 36, 1309660, 0), (36928599892.10665, 36, 1309660, 0),
    ],
}


def fake_results(test_id: str) -> list[tuple]:
    rng = random.Random(test_id)
    cwnd = rng.randint(1_000_000, 1_600_000)
    return [(rng.uniform(30e9, 38e9), rng.randint(30, 50), cwnd, 0) for _ in range(10)]


# --- Data access -------------------------------------------------------------

def fetch_tests() -> list[dict]:
    """Return every test as {"id": str, "cca": str, "parms": dict}."""
    if DB is None:
        rows = SAMPLE_TESTS
    else:
        with DB() as database:
            rows = list(database.query("SELECT id, cca, parms FROM tests"))

    tests = []
    for test_id, cca, parms in rows:
        if isinstance(parms, str):  # json stored as text; jsonb usually arrives as a dict already
            parms = json.loads(parms)
        tests.append({"id": str(test_id), "cca": cca, "parms": parms or {}})
    return tests


def fetch_results(test_id: str) -> dict[str, list[float]]:
    """Return one test's samples as {"throughput": [...], "rtt_ms": [...], ...}."""
    columns = ", ".join(name for name, _, _ in METRICS)
    if DB is None:
        rows = SAMPLE_RESULTS.get(test_id) or fake_results(test_id)
    else:
        with DB() as database:
            # If your DB.query doesn't accept parameters, adapt this call to how it does.
            rows = list(database.query(
                f"SELECT {columns} FROM {RESULTS_TABLE} WHERE test_id = %s ORDER BY id",
                (test_id,),
            ))

    return {
        name: [float(row[i]) if row[i] is not None else math.nan for row in rows]
        for i, (name, _, _) in enumerate(METRICS)
    }


def sort_key(value: str):
    """Sort numbers numerically ("0.1" < "0.5" < "10"), everything else alphabetically."""
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


# --- Widgets -----------------------------------------------------------------

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
    """Scrollable list of test ids with a search box. Ctrl/Shift-click selects several."""

    def __init__(self, parent, on_select):
        super().__init__(parent, text="Tests (Ctrl/Shift-click to compare)", padding=5)
        self.on_select = on_select
        self.ids: list[str] = []

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

    def set_ids(self, ids) -> None:
        self.ids = list(ids)
        self._refresh()

    def get(self) -> list[str]:
        return [self.listbox.get(i) for i in self.listbox.curselection()]

    def _refresh(self) -> None:
        previous = self.get()
        text = self.search_var.get().lower()
        shown = [test_id for test_id in self.ids if text in test_id.lower()]

        self.listbox.delete(0, "end")
        for test_id in shown:
            self.listbox.insert("end", test_id)
        self.count_var.set(f"{len(shown)} of {len(self.ids)} tests shown")

        kept = [test_id for test_id in previous if test_id in shown]
        for test_id in kept:
            self.listbox.selection_set(shown.index(test_id))
        if kept:
            self.listbox.see(shown.index(kept[0]))
        if kept != previous:
            self.on_select(kept)  # some selected tests were filtered away


# --- Main window -------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    root.title("Test viewer")

    # Plots on the left: one subplot per metric, sharing the time axis
    figure = Figure(figsize=(8, 8), constrained_layout=True)
    axes = figure.subplots(len(METRICS), 1, sharex=True)
    canvas = FigureCanvasTkAgg(figure, master=root)
    canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    # Controls on the right
    controls = ttk.Frame(root, padding=10)
    controls.grid(row=0, column=1, sticky="ns")

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    tests: list[dict] = []
    tests_by_id: dict[str, dict] = {}
    results_cache: dict[str, dict] = {}
    param_filters: dict[str, FilterList] = {}
    details_var = tk.StringVar()

    def get_results(test_id: str) -> dict:
        if test_id not in results_cache:
            results_cache[test_id] = fetch_results(test_id)
        return results_cache[test_id]

    def plot_tests(test_ids: list[str]) -> None:
        for axis in axes:
            axis.clear()
            axis.grid(True, alpha=0.3)

        for test_id in test_ids:
            test = tests_by_id[test_id]
            results = get_results(test_id)
            try:
                interval = float(test["parms"].get("interval", 1))
            except ValueError:
                interval = 1.0
            label = f"{test['cca']} {test_id[:8]}"

            for axis, (name, _, scale) in zip(axes, METRICS):
                values = results[name]
                times = [(i + 1) * interval for i in range(len(values))]
                axis.plot(times, [v * scale for v in values], marker=".", label=label)

        for axis, (_, ylabel, _) in zip(axes, METRICS):
            axis.set_ylabel(ylabel)
        axes[-1].set_xlabel("Time (s)")

        if test_ids:
            axes[0].legend(fontsize="small")
            axes[0].set_title(f"{len(test_ids)} test(s) selected")
        else:
            axes[0].set_title("No test selected")

        # Details panel
        if len(test_ids) == 1:
            test = tests_by_id[test_ids[0]]
            parms_text = "\n".join(f"  {key}: {value}" for key, value in sorted(test["parms"].items()))
            details_var.set(f"id: {test['id']}\ncca: {test['cca']}\nparms:\n{parms_text}")
        elif test_ids:
            details_var.set(f"{len(test_ids)} tests selected")
        else:
            details_var.set("No test selected")

        canvas.draw()

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
        test_list.set_ids(test["id"] for test in tests if matches(test))

    cca_filter = FilterList(controls, "CCA", apply_filters)
    cca_filter.grid(row=0, column=0, sticky="ew")

    params_frame = ttk.LabelFrame(controls, text="Parameters", padding=5)
    params_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    test_list = TestList(controls, plot_tests)
    test_list.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
    controls.rowconfigure(2, weight=1)

    ttk.Label(controls, textvariable=details_var, justify="left", font="TkFixedFont").grid(
        row=3, column=0, sticky="w", pady=(10, 0))

    def reload() -> None:
        nonlocal tests
        tests = fetch_tests()
        tests_by_id.clear()
        tests_by_id.update({test["id"]: test for test in tests})
        results_cache.clear()

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

    def close() -> None:
        figure.clear()
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    reload()
    root.mainloop()


if __name__ == "__main__":
    main()