from iperf3 import Iperf3
import configparser
import json


class main:
    TOOLS = [
          "iperf",
          "ss"
    ]

    def __init__(self, config_file='config.ini'):
        self._load_config(config_file)
        self._setup_tools()

    def _load_config(self, config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
        self.config_dict = {section: dict(config.items(section)) for section in config.sections()}

    def _setup_tools(self):
        self.tools = self.config_dict["global_test_settings"]["tools"].split(", ")
        for tool in self.tools:
            if tool not in self.TOOLS:
                raise ValueError(f"Unsupported tool: {tool}")
            match tool:
                case "iperf":
                      self._setup_iperf3()

    def _setup_iperf3(self):
        self.iperf3_tool = Iperf3()
        self.iperf3_tool.setParamters(**self.config_dict.get('iperf_client', {}))

    def _run_iperf3_test(self):
        status = self.iperf3_tool.runTest("example_test")
        if status == 0:
            print(json.dumps(self.iperf3_tool.getTestData("example_test"), indent=2))
        else:
            print("iperf3 test failed")

    def run_tests(self):
        if "iperf" in self.tools:
            self._run_iperf3_test()


test = main()
test.run_tests()
exit(0)