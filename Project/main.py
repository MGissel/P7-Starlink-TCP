from iperf3 import Iperf3
import configparser
import json

# Read the configuration file
config = configparser.ConfigParser()
config.read('config.ini')

config_dict = {section: dict(config.items(section)) for section in config.sections()}

iperf3_tool = Iperf3()
iperf3_tool.setParamters(**config_dict.get('iperf_client', {}))
status = iperf3_tool.runTest("example_test")

if status == 0:
	print(json.dumps(iperf3_tool.getTestData("example_test"), indent=2))
else:
	print("iperf3 test failed")