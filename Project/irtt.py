"""irtt (Isochronous Round-Trip Tester) as a measurement tool that runs alongside iperf3."""
import gzip
import json
import signal
import subprocess
from pathlib import Path

from measurement_tool import MeasurementTool

try:
    import ijson          # streams the JSON; recommended for long tests (pip install ijson)
except ImportError:
    ijson = None

# lost field in irtt's JSON -> number stored in the database
LOST_CODES = {"false": 0, "true_up": 1, "true_down": 2, "true": 3}
LOG_HEADER = "t_ns seqno lost rtt_ns send_delay_ns receive_delay_ns"


class Irtt(MeasurementTool):
    """Sends small UDP packets at a fixed interval and records every round trip.

    Config section [irtt_client]:
        host     = 10.200.0.2   address of the irtt server (inside the namespace)
        interval = 10ms         time between packets
        length   = 0            packet length in bytes (0 = smallest possible)
    The duration is not configured: irtt runs for as long as iperf3.
    """

    runs_alongside = True     # Experiment starts it before iperf3 and stops it afterwards

    VALUE_FLAGS = {
        "interval": "-i",
        "length": "-l",
    }

    def __init__(self):
        self.parameters = {}
        self.test_data = {}
        self._proc = None
        self._output = None
        self._duration = None

    def setParamters(self, **kwargs) -> int:
        self.parameters.update(kwargs)
        return 0

    # --- Running alongside another tool -------------------------------------

    def start(self, output_file: Path, duration_s: float) -> None:
        """Start the irtt client in the background, writing gzipped JSON to output_file."""
        self._output = Path(output_file)
        self._duration = duration_s
        if self._output.exists():
            self._output.unlink()
        args = ["irtt", "client", "-Q", "-d", f"{duration_s:g}s", "-o", str(self._output)]
        for parameter, flag in self.VALUE_FLAGS.items():
            value = self.parameters.get(parameter)
            if value:
                args += [flag, str(value)]
        args.append(self.parameters.get("host", "10.200.0.2"))
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def stop(self, grace_s: float = 10.0) -> int:
        """Wait for irtt to finish; interrupt it if it runs too long. Returns 0 on success."""
        if self._proc is None:
            return 1
        try:
            self._proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            self._proc.send_signal(signal.SIGINT)   # irtt stops early and still writes its results
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        error = self._proc.stderr.read().strip() if self._proc.stderr else ""
        self._proc = None
        if not self._output.exists():
            print(f"irtt produced no results: {error or 'no error output'}")
            return 1
        return 0

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # --- MeasurementTool interface ------------------------------------------

    def runTest(self, test_name: str) -> int:
        """Run irtt on its own (blocking), using parameters['duration'] (seconds)."""
        duration = float(self.parameters.get("duration", 10))
        self.start(Path(f"irtt_{test_name}.json.gz"), duration)
        return self.stop(grace_s=duration + 10)

    def getTestData(self, test_name: str) -> dict:
        return self.test_data.get(test_name, {})


def round_trips(json_file: Path):
    """Yield the round trips from an irtt JSON file (.json or .json.gz) one at a time."""
    opener = gzip.open if str(json_file).endswith(".gz") else open
    with opener(json_file, "rb") as f:
        if ijson is not None:
            yield from ijson.items(f, "round_trips.item")
        else:
            yield from json.load(f).get("round_trips", [])


def irtt_to_log(json_file: Path, log_file: Path, clock_offset_ns: int) -> int:
    """Convert irtt's JSON to a space-separated log in the same format as the probe logs.

    Times are converted to the probe's clock (t_ns = wall clock - clock_offset_ns),
    so irtt and probe samples share one time axis. Returns the number of rows.
    """
    rows = 0
    with open(log_file, "w") as out:
        out.write(LOG_HEADER + "\n")
        for rt in round_trips(json_file):
            wall = rt["timestamps"]["client"]["send"]["wall"]
            delay = rt.get("delay") or {}
            lost = LOST_CODES.get(str(rt.get("lost", "false")).lower(), 3)
            values = [
                int(wall) - clock_offset_ns,
                rt.get("seqno"),
                lost,
                delay.get("rtt"),
                delay.get("send"),
                delay.get("receive"),
            ]
            out.write(" ".join(r"\N" if v is None else str(int(v)) for v in values) + "\n")
            rows += 1
    return rows