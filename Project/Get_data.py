import json
import math
import random
import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")

import psycopg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


try:
    from DB import DB
except ImportError as error:
    print(f"Could not import DB: {error!r}, using sample data")
    DB = None

RESULTS_TABLE = "public.results"

ANY = "(any)"

# (column, axis label, scale factor applied before plotting)
METRICS = [
    ("throughput", "Throughput (Gbit/s)", 1e-9),  # assumes throughput is stored in bit/s
    ("rtt_ms", "RTT (ms)", 1),
    ("cwnd", "cwnd", 1),
    ("retrans", "Retransmits", 1),
]


def fake_results(test_name: str) -> list[tuple]:
    rng = random.Random(test_name)
    cwnd = rng.randint(1_000_000, 1_600_000)
    return [(rng.uniform(30e9, 38e9), rng.randint(30, 50), cwnd, 0) for _ in range(10)]


# --- Data access -------------------------------------------------------------

def fetch_tests() -> list[dict]:
    """Return every test as {"name": str, "cca": str, "parms": dict}."""
    with DB() as database:
        rows = list(database.query("SELECT name, cca, parms FROM public.tests"))

    tests = []
    for test_name, cca, parms in rows:
        if isinstance(parms, str):  # json stored as text; jsonb usually arrives as a dict already
            parms = json.loads(parms)
        tests.append({"name": test_name, "cca": cca, "parms": parms or {}})
    return tests


def fetch_results(test_name: str) -> dict[str, list[float]]:
    """Return one test's samples as {"throughput": [...], "rtt_ms": [...], ...}."""
    columns = ", ".join(name for name, _, _ in METRICS)
    
    with DB() as database:
        rows = list(database.query(
            f"""
            SELECT {columns}
            FROM {RESULTS_TABLE} AS results
            JOIN public.tests AS tests ON tests.id = results.test_id
            WHERE tests.name = %s
            ORDER BY results.id
            """,
            (test_name,),
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

    # Plots on the left: one subplot per metric, sharing the time axis
    figure = Figure(figsize=(8, 8), constrained_layout=True)
    axes = figure.subplots(len(METRICS), 1, sharex=True)
    canvas = FigureCanvasTkAgg(figure, master=root)
    canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    # Controls on the right
    controls = ttk.Frame(root, padding=10)
    controls.grid(row=0, column=1, sticky="ns")

    root.columnconfigure(0, weight=1)
    root.columnconfigure(2, weight=0)
    root.rowconfigure(0, weight=1)

    tests: list[dict] = []
    tests_by_name: dict[str, dict] = {}
    results_cache: dict[str, dict] = {}
    param_filters: dict[str, FilterList] = {}
    details_var = tk.StringVar()
    line_plot_var = tk.BooleanVar(value=False)

    def get_results(test_name: str) -> dict:
        if test_name not in results_cache:
            results_cache[test_name] = fetch_results(test_name)
        return results_cache[test_name]

    def plot_tests(test_names: list[str]) -> None:
        for axis in axes:
            axis.clear()
            axis.grid(True, alpha=0.3)

        for test_name in test_names:
            test = tests_by_name[test_name]
            results = get_results(test_name)
            try:
                interval = float(test["parms"].get("interval", 1))
            except (TypeError, ValueError):
                interval = 1.0
            try:
                omit = max(0.0, float(test["parms"].get("omit", 0)))
            except (TypeError, ValueError):
                omit = 0.0
            samples_to_skip = math.ceil(omit / interval) if interval > 0 else 0
            label = f"{test['cca']} {test_name}"

            for axis, (name, _, scale) in zip(axes, METRICS):
                values = results[name][samples_to_skip:]
                times = [
                    (i + 1) * interval
                    for i in range(samples_to_skip, samples_to_skip + len(values))
                ]
                axis.plot(
                    times,
                    [v * scale for v in values],
                    linestyle="-" if line_plot_var.get() else "none",
                    marker=None if line_plot_var.get() else ".",
                    label=label,
                )

        axes[0].relim()
        axes[0].autoscale_view()
        try:
            x_min = float(x_min_var.get()) if x_min_var.get().strip() else None
            x_max = float(x_max_var.get()) if x_max_var.get().strip() else None
        except ValueError:
            x_min = x_max = None
        current_min, current_max = axes[0].get_xlim()
        axes[0].set_xlim(
            current_min if x_min is None else x_min,
            current_max if x_max is None else x_max,
        )

        for axis, (_, ylabel, _) in zip(axes, METRICS):
            axis.set_ylabel(ylabel)
        axes[-1].set_xlabel("Time (s)")

        if test_names:
            axes[0].legend(fontsize="small")
            axes[0].set_title(f"{len(test_names)} test(s) selected")
        else:
            axes[0].set_title("No test selected")

        # Details panel
        if len(test_names) == 1:
            test = tests_by_name[test_names[0]]
            parms_text = "\n".join(f"  {key}: {value}" for key, value in sorted(test["parms"].items()))
            details_var.set(f"name: {test['name']}\ncca: {test['cca']}\nparms:\n{parms_text}")
        elif test_names:
            details_var.set(f"{len(test_names)} tests selected")
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
        test_list.set_names(test["name"] for test in tests if matches(test))

    cca_filter = FilterList(controls, "CCA", apply_filters)
    cca_filter.grid(row=0, column=0, sticky="ew")

    params_frame = ttk.LabelFrame(controls, text="Parameters", padding=5)
    params_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    test_list = TestList(root, plot_tests)
    test_list.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(0, 10), pady=10)
    controls.rowconfigure(2, weight=1)

    ttk.Label(root, textvariable=details_var, justify="left", font="TkFixedFont").grid(
        row=2, column=2, sticky="nw", padx=(0, 10), pady=(0, 10))

    def reload() -> None:
        nonlocal tests
        tests = fetch_tests()
        tests_by_name.clear()
        tests_by_name.update({test["name"]: test for test in tests})
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