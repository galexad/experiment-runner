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

from ConnectionHandler import ConnectionHandler

import paramiko
import enum
import time
import os


class HOST(enum.Enum):
    GL3 = "GL3"
    GL4 = "GL4"
    GL6 = "GL6"

class Workload(enum.Enum):
    LOW = 25
    MEDIUM = 50
    HIGH = 100

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

    host_name = HOST.GL6.value 

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

    def interrupt_run(self, context, msg):
        self.stop_measurement(context)
        self.stop_run(context)
        output.console_log_FAIL(msg)
        raise Exception(msg)

    def start_run(self, context: RunnerContext) -> None:
        """Perform any activity required for starting the run here.
        For example, starting the target system to measure.
        Activities after starting the run should also be performed here."""

        output.console_log("Config.start_run() called!")

        workload = self.extract_level(context.run_variation['workload'])

        conn_handler = ConnectionHandler(self.host_name, context)
        _, _, password = conn_handler.get_credentials()

        # start deploying the train ticketing system 
        tts_deployment_start = f"tmux new -s train -d 'cd ~/smartwatts-evaluation/train-ticketing-system; echo { password } | sudo -S docker-compose up'"
        if(conn_handler.execute_remote_command(tts_deployment_start, f"Running with {workload} workload") == 0):
            self.interrupt_run(context, "Encountered an error while starting system")

        output.console_log("Waiting for the benchmark system to start up...")
        # sleep for 10 minutes until the deployment is complete
        time.sleep(60 * 10) 
        output.console_log("Benchmark system is up and running")

    def start_measurement(self, context: RunnerContext) -> None:
        """Perform any activity required for starting measurements."""
        output.console_log("Config.start_measurement() called!")
        
        file_name = f"{context.run_variation['run_number']}-{context.run_variation['workload']}"

        # start SmartWatts profiler on GL6
        conn_handler = ConnectionHandler(self.host_name, context)
        _, _, passwordGL6 = conn_handler.get_credentials()

        smartwatts_command = f"tmux new -s smartwatts -d 'cd ~/smartwatts-evaluation/Smartwatts; echo {passwordGL6} | sudo -S docker-compose up'"
        if(conn_handler.execute_remote_command(smartwatts_command, "SmartWatts start") == 0):
            self.interrupt_run(context, "Encountered an error while starting system")


    def interact(self, context: RunnerContext) -> None:
        """Perform any interaction with the running target system here, or block here until the target finishes."""

        output.console_log("Config.interact() called!")
        workload_value = Workload[context.run_variation['workload']].value
        output.console_log(f"Load testing with K6 - {context.run_variation['workload']} workload: {workload_value}")

        os.system(f"for i in $(ls ~/smartwatts-evaluation/k6-test); "
                  f"do k6 run - <~/smartwatts-evaluation/k6-test/$i/script.js --vus {workload_value} --duration 20s ; done")

        output.console_log('Finished load testing')

    def stop_measurement(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping measurements."""

        output.console_log("Config.stop_measurement called!")

    def stop_run(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping the run.
        Activities after stopping the run should also be performed here."""

        output.console_log("Config.stop_run() called!")
        conn_handler = ConnectionHandler(self.host_name, context)

        _, _, password = conn_handler.get_credentials()

        # restart docker and remove the created resources 
        prune_docker_volumes = f"echo {password} | sudo -S docker volume prune"
        conn_handler.execute_remote_command(prune_docker_volumes , "Prune volumes")

        restart_docker_command = f"echo {password} | sudo -S systemctl restart docker.service"
        conn_handler.execute_remote_command(restart_docker_command , "Restart docker system")
        
        # Kill tmux sessions
        conn_handler.execute_remote_command("tmux kill-session -t train", "Kill tmux train session")
        conn_handler.execute_remote_command("tmux kill-session -t smartwatts", "Kill tmux smartwatts session")



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
