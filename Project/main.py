import configparser
import json
import time
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

    def run_tools(self, test_name: str) -> None:
        for name, tool in self.tools.items():
            status = tool.runTest(test_name)
            if status != 0:
                raise RuntimeError(f"{name} test failed")
            print(json.dumps(tool.getTestData(test_name), indent=2))

    def save_iperf_result(self, test_name: str) -> None:
        iperf = self.tools.get("iperf")
        if not isinstance(iperf, Iperf3):
            return
        from DB import DB

        with DB() as database:
            database.save_iperf_test(
                iperf.getTestData(test_name),
                self.config["global_test_settings"]["cca"],
                self.config.get("iperf_client", {}),
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
    network = setup_network_and_theaterq()

    with network.iperf_server() as server:
        time.sleep(1)
        network.ensure_process_started(server)

        experiment = Experiment()
        experiment.run_tools("test_2")
        experiment.save_iperf_result("test_2")


if __name__ == "__main__":
    main()
