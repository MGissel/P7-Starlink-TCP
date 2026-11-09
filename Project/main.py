import configparser
import json
import time
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path

from TQ import TQ
from iperf3 import Iperf3
from irtt import Irtt, irtt_to_log
from network import NetworkNamespace
from ss import SS
from tcpSocket import SocketReader

LIVE_UPLOAD_INTERVAL = 10  # seconds between probe uploads while the test runs


class Experiment:
    """Load project configuration and run the configured measurements."""

    SUPPORTED_TOOLS = {"iperf": Iperf3, "ss": SS, "irtt": Irtt}

    def __init__(self, config_file: str | Path = Path(__file__).with_name("config.ini")):
        self.config = self._load_config(config_file)
        self.tools = self._create_tools()
        self.settings = self.config["global_test_settings"]
        self.test_name = self.settings["name"]

    @staticmethod
    def _load_config(config_file: str | Path) -> dict[str, dict[str, str]]:
        parser = configparser.ConfigParser()
        if not parser.read(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        return {section: dict(parser.items(section)) for section in parser.sections()}

    def _create_tools(self) -> dict[str, Iperf3 | SS | Irtt]:
        configured_tools = self.config["global_test_settings"]["tools"].split(",")
        tools = {}
        for name in (tool.strip() for tool in configured_tools):
            tool_type = self.SUPPORTED_TOOLS.get(name)
            if tool_type is None:
                raise ValueError(f"Unsupported tool: {name}")
            tool = tool_type()
            tool.setParamters(**self.config.get(f"{name}_client", self.config.get(name, {})))
            tools[name] = tool
        return tools

    @property
    def offline(self) -> bool:
        return self.settings.get("offline", "false").lower() == "true"

    @property
    def iperf(self) -> Iperf3:
        iperf = self.tools.get("iperf")
        if not isinstance(iperf, Iperf3):
            raise RuntimeError("This requires the iperf tool")
        return iperf

    @property
    def irtt(self) -> Irtt | None:
        tool = self.tools.get("irtt")
        return tool if isinstance(tool, Irtt) else None

    def iperf_duration(self) -> float:
        try:
            return float(self.iperf.parameters.get("duration", 0))
        except (TypeError, ValueError) as error:
            raise RuntimeError("The iperf duration must be a valid number") from error

    def run_tools(self) -> None:
        """Run the tools one after the other; tools that run alongside (irtt) wrap around them."""
        alongside = {name: tool for name, tool in self.tools.items()
                     if getattr(tool, "runs_alongside", False)}
        # Start slightly before iperf3 and keep going slightly longer, so it covers the whole test
        for name, tool in alongside.items():
            tool.start(irtt_files(self.test_name)[0], self.iperf_duration() + 2)
        try:
            for name, tool in self.tools.items():
                if name in alongside:
                    continue
                status = tool.runTest(self.test_name)
                if status != 0:
                    raise RuntimeError(f"{name} test failed")
        finally:
            for name, tool in alongside.items():
                if tool.stop() != 0:
                    print(f"Warning: {name} did not produce results")

    def convert_irtt(self, clock_offset_ns: int) -> Path | None:
        """Turn irtt's JSON into a log file on the probe's time axis; returns its path."""
        json_file, log_file = irtt_files(self.test_name)
        if not json_file.exists():
            return None
        rows = irtt_to_log(json_file, log_file, clock_offset_ns)
        print(f"irtt: {rows} round trips")
        return log_file

    def db_parameters(self) -> dict:
        """Parameters stored with the test: iperf3's, plus irtt's prefixed with 'irtt_'."""
        parameters = dict(self.iperf.parameters)
        if self.irtt is not None:
            parameters.update({f"irtt_{key}": value for key, value in self.irtt.parameters.items()})
        return parameters

    # --- Database ------------------------------------------------------------

    def create_db_test(self, clock_offset_ns: int):
        """Create the test row before the test starts, so samples can be streamed into it."""
        from DB import DB
        with DB() as database:
            return database.create_test(
                f"{self.test_name} (running)",
                self.settings["cca"],
                self.db_parameters(),
                clock_offset_ns=clock_offset_ns,
            )

    def finish_db_test(self, test_id, probe_complete: bool, irtt_log: Path | None = None) -> None:
        """Add the iperf3 (and irtt) results and give the test its final name."""
        from DB import DB
        with DB() as database:
            database.save_iperf_results(test_id, self.iperf.getTestData(self.test_name))
            if irtt_log is not None:
                rows = database.save_samples(test_id, {"irtt_samples": irtt_log})
                print(f"Uploaded {rows['irtt_samples']} irtt round trips")
            name = self.test_name if probe_complete else f"{self.test_name} (incomplete)"
            database.rename_test(test_id, name)

    def mark_db_test(self, test_id, suffix: str) -> None:
        from DB import DB
        try:
            with DB() as database:
                database.rename_test(test_id, f"{self.test_name} ({suffix})")
        except Exception as error:
            print(f"Could not mark the test as {suffix}: {error!r}")

    def upload_from_files(self) -> None:
        """Upload mode: send a finished test from its local files.

        If the test was already (partly) uploaded live, that version is replaced.
        """
        if self.iperf.load_local_test(self.test_name) != 0:
            raise RuntimeError(f"Could not load local test '{self.test_name}'")

        tcp_log, cubic_log, meta_file = probe_files(self.test_name)
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}

        from DB import DB
        with DB() as database:
            if meta.get("test_id"):
                if database.delete_tests_by_id([meta["test_id"]]):
                    print("Replaced the earlier upload of this test")
            test_id = database.save_iperf_test(
                self.test_name,
                self.iperf.getTestData(self.test_name),
                self.settings["cca"],
                self.db_parameters(),
                clock_offset_ns=meta.get("clock_offset_ns"),
            )
            if tcp_log.exists() and cubic_log.exists():
                tcp_rows, cubic_rows = database.save_probe_samples(test_id, tcp_log, cubic_log)
                print(f"Uploaded {tcp_rows} TCP and {cubic_rows} CUBIC probe samples")
            else:
                print("No probe logs found for this test, uploaded iperf results only")

            irtt_json, irtt_log = irtt_files(self.test_name)
            if irtt_json.exists() and not irtt_log.exists() and meta.get("clock_offset_ns") is not None:
                self.convert_irtt(meta["clock_offset_ns"])
            if irtt_log.exists():
                rows = database.save_samples(test_id, {"irtt_samples": irtt_log})
                print(f"Uploaded {rows['irtt_samples']} irtt round trips")

        meta["test_id"] = str(test_id)
        meta_file.write_text(json.dumps(meta))


PROBE_DIR = Path(__file__).resolve().parent / "probe_logs"


def probe_files(test_name: str) -> tuple[Path, Path, Path]:
    """Log files for one test: TCP samples, CUBIC samples, metadata (clock offset, test id)."""
    return (
        PROBE_DIR / f"{test_name}_tcp.log",
        PROBE_DIR / f"{test_name}_cubic.log",
        PROBE_DIR / f"{test_name}_probe.json",
    )


def irtt_files(test_name: str) -> tuple[Path, Path]:
    """irtt's own JSON output, and the converted log that is uploaded."""
    return (
        PROBE_DIR / f"{test_name}_irtt.json.gz",
        PROBE_DIR / f"{test_name}_irtt.log",
    )


def setup_network_and_theaterq():
    project_root = Path(__file__).resolve().parent.parent
    network = NetworkNamespace()
    network.setup()
    theaterq = TQ()
    theaterq.setParamters(
        trace=project_root / "Project" / "TheaterQ_Traces" / "20260319_mixed_losssampling_eval_dl50.trace",
        interface=network.host_interface,
        handle="1:",
        format="SIMPLE",
        stage="ARM",
        cont="LOOP",
    )
    if theaterq.runTest("network_test") != 0:
        raise RuntimeError("TheaterQ setup failed")

    print("TheaterQ setup completed successfully. Running main tests...")
    return network


def main() -> None:
    experiment = Experiment()
    settings = experiment.settings
    upload = settings.get("upload", settings.get("opload", "false")).lower() == "true"
    test_name = experiment.test_name

    if upload:
        experiment.upload_from_files()
        return

    network = setup_network_and_theaterq()

    PROBE_DIR.mkdir(exist_ok=True)
    tcp_log, cubic_log, meta_file = probe_files(test_name)

    # Offset converts the probe's t_ns (time since boot) to wall-clock time
    clock_offset_ns = time.time_ns() - time.monotonic_ns()

    # Online: create the test now, so the probe samples can be uploaded while it runs
    test_id = None
    if not experiment.offline:
        test_id = experiment.create_db_test(clock_offset_ns)
    meta_file.write_text(json.dumps({
        "clock_offset_ns": clock_offset_ns,
        "test_id": str(test_id) if test_id else None,
    }))

    uploader = None
    with ExitStack() as servers:
        server = servers.enter_context(network.iperf_server())
        irtt_server = servers.enter_context(network.irtt_server()) if experiment.irtt else None
        time.sleep(1)
        network.ensure_process_started(server)
        if irtt_server is not None:
            network.ensure_process_started(irtt_server, "irtt server")

        reader = None
        try:
            reader = SocketReader(tcp_file=tcp_log, cubic_file=cubic_log)
            if test_id is not None:
                from liveUpload import LiveUploader
                uploader = LiveUploader(
                    test_id,
                    {"tcp_samples": tcp_log, "cubic_samples": cubic_log},
                    interval=LIVE_UPLOAD_INTERVAL,
                )
            start_time = datetime.now()
            expected_end_time = start_time + timedelta(seconds=experiment.iperf_duration())
            print(
                f"The test started at {start_time:%H:%M:%S} "
                f"and should end at about {expected_end_time:%H:%M:%S}"
            )
            experiment.run_tools()
        except BaseException:
            # Keep what was uploaded, but mark the test as failed
            if reader is not None:
                reader.stop()
            if uploader is not None:
                uploader.stop(attempts=1)
            if test_id is not None:
                experiment.mark_db_test(test_id, "failed")
            raise
        reader.stop()   # always before uploader.stop(), so the files are complete

    irtt_log = None
    if experiment.irtt:
        try:
            irtt_log = experiment.convert_irtt(clock_offset_ns)
        except Exception as error:   # don't lose the rest of the test over irtt
            print(f"Could not read irtt's results: {error!r}")

    if uploader is None:
        print("Offline mode enabled. Skipping database save.")
        return

    print("Iperf has finished, uploading the last probe samples and the iperf results")
    probe_complete = uploader.stop()
    rows = uploader.rows()
    print(f"Uploaded {rows['tcp_samples']} TCP and {rows['cubic_samples']} CUBIC probe samples")
    try:
        experiment.finish_db_test(test_id, probe_complete, irtt_log)
    except Exception as error:
        print(f"Could not save the iperf results: {error!r}")
        probe_complete = False
        experiment.mark_db_test(test_id, "incomplete")
    if not probe_complete:
        print("Not everything reached the database. Run again with upload = true "
              "to upload this test from the local files.")


if __name__ == "__main__":
    main()