import configparser
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from TQ import TQ
from iperf3 import Iperf3
from network import NetworkNamespace
from ss import SS


class Experiment:
    """Load project configuration and run the configured measurements."""

    SUPPORTED_TOOLS = {"iperf": Iperf3, "ss": SS}

    def __init__(self, config_file: str | Path = Path(__file__).with_name("config.ini")):
        self.config = self._load_config(config_file)
        self.tools = self._create_tools()

    @staticmethod
    def _load_config(config_file: str | Path) -> dict[str, dict[str, str]]:
        parser = configparser.ConfigParser()
        if not parser.read(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        return {section: dict(parser.items(section)) for section in parser.sections()}

    def _create_tools(self) -> dict[str, Iperf3 | SS]:
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

    def run_tools(self) -> None:
        test_name = self.config["global_test_settings"]["name"]
        for name, tool in self.tools.items():
            status = tool.runTest(test_name)
            if status != 0:
                raise RuntimeError(f"{name} test failed")
            #print(json.dumps(tool.getTestData(test_name), indent=2))

    def save_iperf_result(self, force_upload: bool = False) -> None:
        test_name = self.config["global_test_settings"]["name"]
        iperf = self.tools.get("iperf")
        if not isinstance(iperf, Iperf3):
            return
        if (
            self.config["global_test_settings"].get("offline", "false").lower() == "true"
            and not force_upload
        ):
            print("Offline mode enabled. Skipping database save.")
            return
        from DB import DB
        with DB() as database:
            database.save_iperf_test(
                self.config["global_test_settings"]["name"],
                iperf.getTestData(test_name),
                self.config["global_test_settings"]["cca"],
                iperf.parameters,
            )


def setup_network_and_theaterq() -> None:
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
    with network.iperf_server() as server:
        time.sleep(1)
        network.ensure_process_started(server)
        time.sleep(5)


def main() -> None:
    experiment = Experiment()
    settings = experiment.config["global_test_settings"]
    upload = settings.get("upload", settings.get("opload", "false")).lower() == "true"

    if upload:
        iperf = experiment.tools.get("iperf")
        if not isinstance(iperf, Iperf3):
            raise RuntimeError("Upload mode requires the iperf tool")
        test_name = settings["name"]
        if iperf.load_local_test(test_name) != 0:
            raise RuntimeError(f"Could not load local test '{test_name}'")
        experiment.save_iperf_result(force_upload=True)
        return

    network = setup_network_and_theaterq()

    with network.iperf_server() as server:
        time.sleep(1)
        network.ensure_process_started(server)
        start_time = datetime.now()
        try:
            duration = float(experiment.tools["iperf"].parameters.get("duration", 0))
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("The iperf duration must be a valid number") from error
        expected_end_time = start_time + timedelta(seconds=duration)
        print(
            f"The test started at {start_time:%H:%M:%S} "
            f"and should end at about {expected_end_time:%H:%M:%S}"
        )
        experiment.run_tools()
        print("Iperf has finished, now uploading to database")
        experiment.save_iperf_result()


if __name__ == "__main__":
    main()
