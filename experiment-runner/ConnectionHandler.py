from ProgressManager.Output.OutputProcedure import OutputProcedure as output

import os
import paramiko

class ConnectionHandler:
    def __init__(self, host_name):
        self.host_name = host_name

    def execute_remote_command(self, command, command_name):
        con = self.connect_to_host()
        output.console_log(command_name)
        req, out, err = con.exec_command(command)
        err = err.read()

        if err != b'':
            output.console_log(err)
            return 0

        output.console_log(f"'{command_name}' command successfully executed")
        return 1

    def connect_to_host(self):
        host, username, password = self.get_credentials()
        # connect to server
        con = paramiko.SSHClient()
        con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        con.connect(host, username = username, password = password)
        output.console_log(f"Connection successful to {self.host_name}")

        return con

    def get_credentials(self):
        # declare credentials
        host_name = self.host_name
        host = os.getenv(f"{host_name}_HOST")
        username = os.getenv(f"{host_name}_USER")
        password = os.getenv(f"{host_name}_PASSWORD")

        if not password or not username or not host:
            raise Exception('No environment variables set for credentials')

        return host, username, password

    def get_containers_count(self):
        conn = self.connect_to_host()
        _, _, password = self.get_credentials()
        _, number_of_containers_buf, err = conn.exec_command(f" echo {password} | sudo -S docker ps | wc -l")
        number_of_containers = int(number_of_containers_buf.read().strip())
        output.console_log(f"Found {number_of_containers} running after sleeping")

        return number_of_containers

    def start_wattsuppro_logger(self, file_name, context):
        # start WattsUp profiler on current host
        file_name = f"{context.run_variation['run_number']}-{context.run_variation['workload']}"

        _, _, password = self.get_credentials()
        watssup_command = f"echo {password} | sudo -S ~/smartwatts-evaluation/wattsup/start_wattsup.sh {file_name} {context.run_variation['run_number']} train-ticket"
        self.execute_remote_command(watssup_command, f"Start WattsupPro on {self.host_name}")
