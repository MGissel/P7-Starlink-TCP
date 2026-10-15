from pathlib import Path
import subprocess

from measurement_tool import MeasurementTool


class TQ(MeasurementTool):
	"""Configure and run a TheaterQ trace through tc."""

	def __init__(self, loader=None):
		self.parameters = {}
		self.test_data = {}
		self.module = (
			Path(__file__).resolve().parent.parent
			/ "TheaterQ"
			/ "theaterq_lkm"
			/ "sch_theaterq.ko"
		)
		self.tc_lib_dir = Path(__file__).resolve().parent.parent / "TheaterQ" / "theaterq_tc" / "tclib"
		self.loader = Path(loader) if loader else None

	def setParamters(self, **kwargs) -> int:
		"""Set TheaterQ parameters from configuration values."""
		self.parameters.update(kwargs)
		return 0

	def _tc_command(self, *arguments):
		return [
			"sudo",
			"env",
			f"TC_LIB_DIR={self.parameters.get('tc_lib_dir', self.tc_lib_dir)}",
			"tc",
			*arguments,
		]

	def _run_command(self, command, **kwargs):
		return subprocess.run(
			command,
			capture_output=True,
			text=True,
			check=False,
			**kwargs,
		)

	def _load_kernel_module(self):
		"""Load the TheaterQ qdisc module when it is not already loaded."""
		module_name = self.module.stem
		loaded = subprocess.run(
			["lsmod"], capture_output=True, text=True, check=False
		)
		if module_name in loaded.stdout:
			return True

		module = self.parameters.get("module", self.module)
		result = subprocess.run(
			["sudo", "-n", "insmod", str(module)],
			capture_output=True,
			text=True,
			check=False,
		)
		if result.returncode != 0:
			message = result.stderr.strip()
			if "password is required" in message:
				message = "run 'sudo insmod {}' once before starting the test".format(module)
			print(f"Could not load TheaterQ kernel module: {message}")
			return False
		return True

	def _command(self):
		trace = self.parameters.get("trace") or self.parameters.get("trace_file")
		if not trace:
			raise ValueError("TheaterQ requires a 'trace' or 'trace_file' parameter")

		interface = self.parameters.get("interface", "lo")
		handle = self.parameters.get("handle", "1:")
		return Path(trace), interface, handle

	def runTest(self, test_name: str) -> int:
		"""Load and start the configured TheaterQ trace."""
		if str(self.parameters.get("auto_load", "true")).lower() == "true":
			if not self._load_kernel_module():
				return 1

		try:
			trace, interface, handle = self._command()
		except ValueError as error:
			print(f"TheaterQ configuration error: {error}")
			return 1

		if not trace.is_file():
			print(f"TheaterQ trace file not found: {trace}")
			return 1

		trace_format = str(self.parameters.get("format", "EXTENDED")).upper()
		stage = str(self.parameters.get("stage", "RUN")).upper()
		continuation = str(self.parameters.get("cont", "HOLD")).upper()
		device = f"/dev/theaterq:{interface}:{str(handle).rstrip(':')}:0"
		commands = []

		clear_command = self._tc_command(
			"qdisc", "replace", "dev", str(interface), "root", "handle", str(handle),
			"theaterq", "stage", "CLEAR", "ingest", trace_format,
		)
		commands.append(clear_command)
		result = self._run_command(clear_command)
		if result.returncode != 0:
			return self._store_failure(test_name, commands, result)

		with trace.open("rb") as trace_stream:
			ingest_command = ["sudo", "tee", device]
			commands.append(ingest_command)
			result = subprocess.run(
				ingest_command,
				stdin=trace_stream,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=False,
				check=False,
			)
		if result.returncode != 0:
			return self._store_failure(test_name, commands, result)

		run_command = self._tc_command(
			"qdisc", "change", "dev", str(interface), "root", "handle", str(handle),
			"theaterq", "stage", stage, "cont", continuation,
		)
		commands.append(run_command)
		result = self._run_command(run_command)
		if result.returncode != 0:
			return self._store_failure(test_name, commands, result)

		self.test_data[test_name] = {
			"commands": commands,
			"returncode": 0,
			"stdout": result.stdout,
			"stderr": result.stderr,
		}
		return 0

	def _store_failure(self, test_name, commands, result):
		stderr = result.stderr.decode() if isinstance(result.stderr, bytes) else result.stderr
		self.test_data[test_name] = {
			"commands": commands,
			"returncode": result.returncode,
			"stdout": "",
			"stderr": stderr,
		}
		print(f"TheaterQ failed: {stderr.strip()}")
		return 1

	def getTestData(self, test_name: str) -> dict:
		"""Get the command result for a TheaterQ test."""
		return self.test_data.get(test_name, {})
