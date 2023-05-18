from EventManager.Models.RunnerEvents import RunnerEvents
from EventManager.EventSubscriptionController import EventSubscriptionController
from ConfigValidator.Config.Models.RunTableModel import RunTableModel
from ConfigValidator.Config.Models.FactorModel import FactorModel
from ConfigValidator.Config.Models.RunnerContext import RunnerContext
from ConfigValidator.Config.Models.OperationType import OperationType
from ExtendedTyping.Typing import SupportsStr
from ProgressManager.Output.OutputProcedure import OutputProcedure as output

from typing import Dict, List, Any, Optional
from pathlib import Path
from os.path import dirname, realpath

import paramiko
import enum
import os


class HOST(enum.Enum):
    GL3 = "GL3"
    GL4 = "GL4"
    GL6 = "GL6"


class Workload(enum.Enum):
    LOW = 25
    MEDIUM = 50
    HIGH = 100

def remote_command(connection_name, command, measurement_name):
    con = get_paramiko_connection(connection_name)

    output.console_log(f'Starting { measurement_name } meter')
    stdin, stdout, stderr = con.exec_command(command)
    err = stderr.read()
    if err != b'':
        output.console_log(err)
    output.console_log(f'{ measurement_name } successfully executed')

def get_paramiko_connection(connection_name):
    host, username, password = get_credentials(connection_name)
    # connect to server
    con = paramiko.SSHClient()
    con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    con.connect(host, username=username, password=password)
    output.console_log(f"Connection successful to {connection_name}")

    return con

def get_credentials(host_name):
    # declare credentials
    host = os.getenv(f"{host_name}_HOST")
    username = os.getenv(f"{host_name}_USER")
    password = os.getenv(f"{host_name}_PASSWORD")
    print(username)
    print(password)
    print(host)

    if not password or not username or not host:
        raise Exception('No environment variables set for credentials')

    return host, username, password


class RunnerConfig:
    ROOT_DIR = Path(dirname(realpath(__file__)))

    # ================================ USER SPECIFIC CONFIG ================================
    """The name of the experiment."""
    name:                       str             = "new_runner_experiment"

    """The path in which Experiment Runner will create a folder with the name `self.name`, in order to store the
    results from this experiment. (Path does not need to exist - it will be created if necessary.)
    Output path defaults to the config file's path, inside the folder 'experiments'"""
    results_output_path:        Path            = ROOT_DIR / 'experiments'

    """Experiment operation type. Unless you manually want to initiate each run, use `OperationType.AUTO`."""
    operation_type:             OperationType   = OperationType.AUTO

    """The time Experiment Runner will wait after a run completes.
    This can be essential to accommodate for cooldown periods on some systems."""
    time_between_runs_in_ms:    int             = 1000

    # Dynamic configurations can be one-time satisfied here before the program takes the config as-is
    # e.g. Setting some variable based on some criteria
    def __init__(self):
        """Executes immediately after program start, on config load"""

        EventSubscriptionController.subscribe_to_multiple_events([
            (RunnerEvents.BEFORE_EXPERIMENT, self.before_experiment),
            (RunnerEvents.BEFORE_RUN       , self.before_run       ),
            (RunnerEvents.START_RUN        , self.start_run        ),
            (RunnerEvents.START_MEASUREMENT, self.start_measurement),
            (RunnerEvents.INTERACT         , self.interact         ),
            (RunnerEvents.STOP_MEASUREMENT , self.stop_measurement ),
            (RunnerEvents.STOP_RUN         , self.stop_run         ),
            (RunnerEvents.POPULATE_RUN_DATA, self.populate_run_data),
            (RunnerEvents.AFTER_EXPERIMENT , self.after_experiment )
        ])
        self.run_table_model = None  # Initialized later

        output.console_log("Custom config loaded")


    def create_run_table_model(self) -> RunTableModel:
        """Create and return the run_table model here. A run_table is a List (rows) of tuples (columns),
        representing each run performed"""        
        runs_list = ['r{}'.format(i) for i in range(1, 101)]
        self.run_table_model = RunTableModel(
            factors=[
                FactorModel("run_number", runs_list),
                FactorModel("workload", ['HIGH', 'MEDIUM', 'LOW']),
            ],
            data_columns=[]
        )
        
        return self.run_table_model

    def before_experiment(self) -> None:
        """Perform any activity required before starting the experiment here
        Invoked only once during the lifetime of the program."""

        output.console_log("Config.before_experiment() called!")

    def before_run(self) -> None:
        """Perform any activity required before starting a run.
        No context is available here as the run is not yet active (BEFORE RUN)"""

        output.console_log("Config.before_run() called!")


    def extract_level(self, level):
        return level.lower()

    def start_run(self, context: RunnerContext) -> None:
        """Perform any activity required for starting the run here.
        For example, starting the target system to measure.
        Activities after starting the run should also be performed here."""

        output.console_log("Config.start_run() called!")

        host, username, password = get_credentials('GL6')

        # connect to server
        con = paramiko.SSHClient()
        con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        con.connect(host, username=username, password=password)

        output.console_log("Successfully connected to GL6")

        workload = self.extract_level(context.run_variation['workload'])
        output.console_log(f"Running with {workload} workload")

        # start deploying the train ticketing system 
        stdin, stdout, stderr = con.exec_command("tmux new -s train -d 'cd ~/smartwatts-evaluation/train-ticketing-system; echo {password} | sudo -S docker-compose up'")

        output.console_log(f"Output: {stdout.read()}")

        err = stderr.read()
        if err != b'':
            output.console_log(err)
            self.interupt_run(context, "Encountered an error while starting system")

    def start_measurement(self, context: RunnerContext) -> None:
        """Perform any activity required for starting measurements."""
        output.console_log("Config.start_measurement() called!")
        
        file_name = f"{context.run_variation['run_number']}-{context.run_variation['workload']}"

        # start SmartWatts profiler on GL6
        output.console_log("Retrieving credentials for GL6}")

        _, _, passwordGL6 = get_credentials('GL6')
        smartwatts_command = f"cd ~/smartwatts-evaluation/train-ticketing-system; echo { passwordGL6 } | sudo docker-compose  { file_name } {context.run_variation['run_number']}"
        remote_command('GL6', smartwatts_command, "SmartWatts start")

    def interact(self, context: RunnerContext) -> None:
        """Perform any interaction with the running target system here, or block here until the target finishes."""

        output.console_log("Config.interact() called!")

    def stop_measurement(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping measurements."""

        output.console_log("Config.stop_measurement called!")

    def stop_run(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping the run.
        Activities after stopping the run should also be performed here."""

        output.console_log("Config.stop_run() called!")

        host, username, password = get_credentials('GL6')

        # connect to server
        con = paramiko.SSHClient()
        con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        con.connect(host, username=username, password=password)

        output.console_log("Connection successful")
        output.console_log('Prune volumes')

        stdin, stdout, stderr = con.exec_command(f"echo { password } | sudo docker volume prune")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Restart docker system')

        stdin, stdout, stderr = con.exec_command(f"echo {password} | sudo -S systemctl restart docker.service")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Kill tmux session')

        stdin, stdout, stderr = con.exec_command(f"tmux kill-session -t train")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Kill netdata if needed')

        stdin, stdout, stderr = con.exec_command(f"echo {password} | sudo -S killall netdata")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

    def populate_run_data(self, context: RunnerContext) -> Optional[Dict[str, SupportsStr]]:
        """Parse and process any measurement data here.
        You can also store the raw measurement data under `context.run_dir`
        Returns a dictionary with keys `self.run_table_model.data_columns` and their values populated"""

        output.console_log("Config.populate_run_data() called!")
        return None

    def after_experiment(self) -> None:
        """Perform any activity required after stopping the experiment here
        Invoked only once during the lifetime of the program."""

        output.console_log("Config.after_experiment() called!")

    # ================================ DO NOT ALTER BELOW THIS LINE ================================
    experiment_path:            Path             = None
