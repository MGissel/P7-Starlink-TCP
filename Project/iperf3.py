from measurement_tool import MeasurementTool
import json
import subprocess
from datetime import datetime
from pathlib import Path

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
        "cca": "-C",
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
        logfile = None

        for parameter, flag in self.VALUE_FLAGS.items():
            value = self.parameters.get(parameter)
            if value:
                if parameter == "logfile":
                    logfile = self._new_logfile_path(value, test_name)
                    value = logfile
                test_parameters.extend([flag, str(value)])

        for parameter, flag in self.BOOLEAN_FLAGS.items():
            value = self.parameters.get(parameter, "false").lower()
            if value == "true":
                test_parameters.append(flag)

        try:
            result = subprocess.run(
                test_parameters,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            print(f"iperf3 failed: {error.stderr.strip()}")
            return 1

        output = result.stdout
        if logfile:
            output = Path(logfile).read_text()

        try:
            decoder = json.JSONDecoder()
            position = 0
            parsed_output = None
            while position < len(output):
                while position < len(output) and output[position].isspace():
                    position += 1
                if position >= len(output):
                    break
                parsed_output, end = decoder.raw_decode(output, position)
                position = end
            if parsed_output is None:
                raise json.JSONDecodeError("empty output", output, 0)
            self.test_data[test_name] = parsed_output
        except json.JSONDecodeError:
            print("iperf3 did not produce valid JSON output")
            return 1
        return 0

    @staticmethod
    def _new_logfile_path(logfile: str | Path, test_name: str) -> Path:
        """Create a unique logfile path without changing the configured base name."""
        path = Path(logfile)
        safe_test_name = "".join(
            character if character.isalnum() or character in ("-", "_") else "_"
            for character in test_name
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return path.with_name(f"{path.stem}_{safe_test_name}_{timestamp}{path.suffix}")

    def getTestData(self, test_name: str) -> dict:
        """Get the test data for the given test name."""
        return self.test_data.get(test_name, {})