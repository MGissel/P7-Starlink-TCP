from measurement_tool import MeasurementTool
import json
import subprocess

class Iperf3(MeasurementTool):
    """Implementation of the MeasurementTool interface for iperf3."""

    VALUE_FLAGS = {
        "host": "-c",
        "port": "-p",
        "interval": "-i",
        "format": "-f",
        "duration": "-t",
        "bytes": "-n",
        "bandwidth": "-b",
        "parallel": "-P",
        "omit": "-O",
        "logfile": "--logfile",
    }
    BOOLEAN_FLAGS = {
        "json": "--json",
        "verbose": "-V",
        "reverse": "-R",
        "bidir": "--bidir",
        "zerocopy": "-Z",
    }

    def __init__(self):
        self.parameters = {}
        self.test_data = {}

    def setParamters(self, **kwargs) -> int:
        """Set parameters for the iperf3 measurement tool."""
        self.parameters.update(kwargs)
        return 0  # Return 0 to indicate success

    def runTest(self, test_name: str) -> int:
        """Run the iperf3 test with the given name."""
        test_parameters = ['iperf3']

        for parameter, flag in self.VALUE_FLAGS.items():
            value = self.parameters.get(parameter)
            if value:
                test_parameters.extend([flag, str(value)])

        for parameter, flag in self.BOOLEAN_FLAGS.items():
            value = self.parameters.get(parameter, "false").lower()
            if value == "true":
                test_parameters.append(flag)

        result = subprocess.run(
            test_parameters,
            capture_output=True,
            text=True,
            check=True,
        )
        self.test_data[test_name] = json.loads(result.stdout)
        return 0

    def getTestData(self, test_name: str) -> dict:
        """Get the test data for the given test name."""
        return self.test_data.get(test_name, {})