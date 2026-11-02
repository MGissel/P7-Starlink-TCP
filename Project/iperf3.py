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
        parameters_file = None

        for parameter, flag in self.VALUE_FLAGS.items():
            value = self.parameters.get(parameter)
            if value:
                if parameter == "logfile":
                    logfile = self._new_logfile_path(value, test_name)
                    parameters_file = logfile.with_name(
                        f"parms_{self._safe_test_name(test_name)}.log"
                    )
                    if logfile.exists():
                        print(f"File name: {logfile} already exists. Give the test a new name.")
                        return 1
                    if parameters_file.exists():
                        print(
                            f"File name: {parameters_file} already exists. "
                            "Give the test a new name."
                        )
                        return 1
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
            if parameters_file:
                parameters_file.write_text(
                    json.dumps(self.parameters, indent=2) + "\n",
                    encoding="utf-8",
                )
        except json.JSONDecodeError:
            print("iperf3 did not produce valid JSON output")
            return 1
        return 0

    def load_local_test(self, test_name: str) -> int:
        """Load a previously saved iperf3 result and its parameters."""
        logfile = self._new_logfile_path(self.parameters.get("logfile", "output.log"), test_name)
        parameters_file = logfile.with_name(
            f"parms_{self._safe_test_name(test_name)}.log"
        )

        if not logfile.exists():
            print(f"File name: {logfile} does not exist.")
            return 1
        if not parameters_file.exists():
            print(f"File name: {parameters_file} does not exist.")
            return 1

        try:
            self.test_data[test_name] = json.loads(logfile.read_text(encoding="utf-8"))
            self.parameters = json.loads(parameters_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"Could not load local test '{test_name}': {error}")
            return 1
        return 0

    @staticmethod
    def _new_logfile_path(logfile: str | Path, test_name: str) -> Path:
        """Create a unique logfile path without changing the configured base name."""
        path = Path(logfile)
        safe_test_name = Iperf3._safe_test_name(test_name)
        return path.with_name(f"{path.stem}_{safe_test_name}{path.suffix}")

    @staticmethod
    def _safe_test_name(test_name: str) -> str:
        return "".join(
            character if character.isalnum() or character in ("-", "_") else "_"
            for character in test_name
        )

    def getTestData(self, test_name: str) -> dict:
        """Get the test data for the given test name."""
        return self.test_data.get(test_name, {})