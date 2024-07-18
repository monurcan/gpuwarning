import argparse
import datetime
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List

import numpy as np

from teams_sender import TeamsSender
from warning_sender_interface import WarningSender


@dataclass
class GPUWarningBotConfig:
    check_period: int
    warn_after: int
    warning_interval: int
    machine_name: str
    people: list


class TerminalSender(WarningSender):
    def send_warning(self, gpu_id, pid_gpu_memory_list):
        print("================================================================")
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[{self.machine_name}] Utilization 0% at GPU {gpu_id}, Time: {current_time}"
        )
        for pid in pid_gpu_memory_list:
            print(
                f"- Related People: {pid['people']}, PID: {pid['pid']}, GPU Memory: {pid['gpu_memory']}, PWD: {pid['pwd']}, Command: {pid['cmd']}"
            )


class FileSender(WarningSender):
    def send_warning(self, gpu_id, pid_gpu_memory_list):
        with open("logs.txt", "a") as f:
            f.write(
                "================================================================\n"
            )
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(
                f"[{self.machine_name}] Utilization 0% at GPU {gpu_id}, Time: {current_time}\n"
            )
            for pid in pid_gpu_memory_list:
                f.write(
                    f"- Related People: {pid['people']}, PID: {pid['pid']}, GPU Memory: {pid['gpu_memory']}, PWD: {pid['pwd']}, Command: {pid['cmd']}\n"
                )


class GPUWarningBot:
    def __init__(
        self, config: GPUWarningBotConfig, senders: List[WarningSender] = None
    ):
        self.config = config
        self.subscribed_senders = senders or [FileSender(config.machine_name)]

    def exec_command(self, command):
        return subprocess.check_output(command.split(" ")).decode("utf-8")

    def get_pids_by_gpu_id(self, smi_string):
        last_separator_index = smi_string.rfind(
            "|=======================================================================================|"
        )

        if last_separator_index == -1:
            return []

        gpu_info_text = smi_string[last_separator_index:]
        gpu_info_lines = gpu_info_text.strip().split("\n")
        gpu_info_lines = [
            line.replace("|", "").strip() for line in gpu_info_lines[1:-1]
        ]
        gpu_info_lines = [
            line for line in gpu_info_lines if line[0].isdigit()
        ]  # Eliminate "no processes found" lines

        gpu_id_to_pids = defaultdict(list)
        for line in gpu_info_lines:
            if "/usr/lib/xorg/Xorg" in line:
                continue

            line_splitted = line.split()
            gpu_id = int(line_splitted[0])
            pid = int(line_splitted[3])
            gpu_memory = line_splitted[-1]
            gpu_id_to_pids[gpu_id].append(
                {
                    "pid": pid,
                    "gpu_memory": gpu_memory,
                }
            )

        return gpu_id_to_pids

    def detail_from_pid_ids(self, pid_gpu_memory_list):
        for pid in pid_gpu_memory_list:
            pid["cmd"] = (
                self.exec_command(f"ps -o cmd fp {pid['pid']}").strip().split("\n")[-1]
            )

            pid["pwd"] = "".join(
                self.exec_command(f"pwdx {pid['pid']}").strip().split(": ")[1:]
            )

            pid["people"] = self.find_related_people(pid["cmd"], pid["pwd"])

    def find_related_people(self, cmd, pwd):
        result_people = set()
        for person in self.config.people:
            person_name_parts = [
                part.lower() for part in person.split(" ") if part != ""
            ]
            for person_name_part in person_name_parts:
                if person_name_part in cmd.lower() or person_name_part in pwd.lower():
                    result_people.add(person)

        return result_people

    def send_notification(self, gpu_id, pid_gpu_memory_list):
        self.detail_from_pid_ids(pid_gpu_memory_list)
        for sender in self.subscribed_senders:
            sender.send_warning(gpu_id, pid_gpu_memory_list)

    def start(self):
        zero_utilization_counter = None
        last_warnings = None

        while True:
            utilization_outputs_str = self.exec_command(
                "nvidia-smi --query-gpu=index,utilization.gpu --format=csv,noheader"
            )

            utilization_outputs = np.array(
                [
                    int(line.split(", ")[-1].strip(" %"))
                    for line in utilization_outputs_str.strip().split("\n")
                ]
            )

            if zero_utilization_counter is None:
                zero_utilization_counter = [0] * len(utilization_outputs)

            if last_warnings is None:
                last_warnings = np.array([float("inf")] * len(utilization_outputs))

            zero_utilization_counter += (
                utilization_outputs == 0
            ) * self.config.check_period
            zero_utilization_counter[utilization_outputs != 0] = 0

            last_warnings += self.config.check_period

            send_notification_ = (last_warnings >= self.config.warning_interval) & (
                zero_utilization_counter >= self.config.warn_after
            )

            send_notification_gpu_ids = np.nonzero(send_notification_)[0]

            if len(send_notification_gpu_ids) > 0:
                gpu_id_pid_map = self.get_pids_by_gpu_id(
                    self.exec_command("nvidia-smi")
                )

            for gpu_id in send_notification_gpu_ids:
                last_warnings[gpu_id] = 0
                if gpu_id_pid_map[gpu_id]:
                    self.send_notification(gpu_id, gpu_id_pid_map[gpu_id])
                else:
                    zero_utilization_counter[gpu_id] = 0

            time.sleep(self.config.check_period)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="GPU Utilization Warning Bot. Execute with sudo!"
    )
    parser.add_argument("--check_period", type=int, default=25, help="(seconds)")
    parser.add_argument("--warn_after", type=int, default=350, help="(seconds)")
    parser.add_argument(
        "--warning_interval",
        type=int,
        default=3600,
        help="(seconds) if we already sent a warning in less than 'warning_interval' ago, then, we will do nothing",
    )
    parser.add_argument("--machine_name", type=str, required=True)
    parser.add_argument(
        "--people",
        default="doruk ozer,alperen inci,utku mert topcuoglu,baran cengiz,burak mandira,cagri eser,mehmet onurcan kaya,sezai artun ozyegin",
        help="comma separated list of people",
    )
    args = parser.parse_args()

    gpu_bot_config = GPUWarningBotConfig(
        check_period=args.check_period,
        warn_after=args.warn_after,
        warning_interval=args.warning_interval,
        machine_name=args.machine_name,
        people=[person.strip() for person in args.people.split(",")],
    )
    warning_senders = [
        TerminalSender(gpu_bot_config.machine_name),
        FileSender(gpu_bot_config.machine_name),
        TeamsSender(gpu_bot_config.machine_name),
    ]
    gpu_bot = GPUWarningBot(gpu_bot_config, warning_senders)
    gpu_bot.start()

    # for testing
    # gpu_id_pid_map = gpu_bot.get_pids_by_gpu_id(gpu_bot.exec_command("nvidia-smi"))
    # gpu_bot.send_notification(5, gpu_id_pid_map[5])
