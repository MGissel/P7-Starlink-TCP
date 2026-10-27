import random
import tkinter as tk
from tkinter import ttk

import matplotlib

matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# --- Data access -------------------------------------------------------------
# Replace these two functions with your real database queries, e.g.:
#
#   def fetch_cca_values():
#       with DB() as database:
#           results = database.query("SELECT DISTINCT cca FROM tests")
#       return [row[0] for row in results]

def fetch_cca_values() -> list[str]:
    """Fake data: a long list of CCA names to test scrolling and searching."""
    bases = ["cubic", "reno", "bbr", "bbr2", "vegas", "westwood", "hybla", "illinois", "htcp", "yeah"]
    variants = ["default", "tuned", "ecn", "pacing", "lowlat", "highbdp"]
    return [f"{base}-{variant}" for base in bases for variant in variants]


def fetch_results(cca: str) -> tuple[list[float], list[float]]:
    """Fake throughput-over-time data. Same CCA name always gives the same curve."""
    rng = random.Random(cca)
    target = rng.uniform(50, 200)
    speed = rng.uniform(0.05, 0.3)
    times, throughput = [], []
    value = 0.0
    for step in range(300):
        t = step * 0.1
        value += (target - value) * speed + rng.gauss(0, target * 0.05)
        if rng.random() < 0.01:  # occasional loss event
            value *= 0.5
        times.append(t)
        throughput.append(max(value, 0))
    return times, throughput


# --- Searchable list widget --------------------------------------------------

def build_cca_selector(parent, on_select):
    frame = ttk.Frame(parent)

    search_var = tk.StringVar()
    ttk.Label(frame, text="Search CCA:").grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Entry(frame, textvariable=search_var).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 5))

    listbox = tk.Listbox(frame, height=15, exportselection=False)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    listbox.grid(row=2, column=0, sticky="nsew")
    scrollbar.grid(row=2, column=1, sticky="ns")

    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(2, weight=1)

    all_values: list[str] = []

    def refresh(*_):
        text = search_var.get().lower()
        listbox.delete(0, "end")
        for value in all_values:
            if text in value.lower():
                listbox.insert("end", value)

    def set_values(values):
        all_values[:] = sorted(values)
        refresh()

    def get_selected():
        selection = listbox.curselection()
        return listbox.get(selection[0]) if selection else None

    search_var.trace_add("write", refresh)
    listbox.bind("<<ListboxSelect>>", lambda e: on_select(get_selected()))

    return frame, set_values, get_selected


# --- Main window -------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    root.title("CCA viewer")

    # Plot on the left
    figure = Figure(figsize=(7, 5))
    axis = figure.add_subplot()
    canvas = FigureCanvasTkAgg(figure, master=root)
    plot_widget = canvas.get_tk_widget()
    plot_widget.grid(row=0, column=0, sticky="nsew")

    # Controls on the right
    controls = ttk.Frame(root, padding=10)
    controls.grid(row=0, column=1, sticky="ns")

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    status_var = tk.StringVar(value="Select a CCA")

    def draw(cca: str | None) -> None:
        axis.clear()
        if cca is not None:
            times, throughput = fetch_results(cca)
            axis.plot(times, throughput)
            axis.set_title(cca)
            status_var.set(f"Showing: {cca}")
        else:
            axis.set_title("No CCA selected")
        axis.set_xlabel("Time (s)")
        axis.set_ylabel("Throughput (Mbit/s)")
        axis.grid(True, alpha=0.3)
        canvas.draw()

    selector, set_cca_values, get_selected_cca = build_cca_selector(controls, draw)
    selector.grid(row=0, column=0, sticky="nsew")
    controls.rowconfigure(0, weight=1)

    def reload_values() -> None:
        set_cca_values(fetch_cca_values())
        status_var.set("CCA list reloaded")

    ttk.Button(controls, text="Reload list", command=reload_values).grid(row=1, column=0, sticky="ew", pady=(10, 0))
    ttk.Label(controls, textvariable=status_var).grid(row=2, column=0, sticky="w", pady=(5, 0))

    def close() -> None:
        figure.clear()
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    set_cca_values(fetch_cca_values())
    draw(None)
    root.mainloop()


if __name__ == "__main__":
    main()