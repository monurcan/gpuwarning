import datetime
import json
import threading
import time

import requests

from access_token_provider import get_access_token
from warning_sender_interface import WarningSender


class TeamsSender(WarningSender):
    def __init__(self, machine_name):
        super().__init__(machine_name)

        self.access_token = get_access_token()
        self.token_refresh_thread = threading.Thread(target=self.refresh_token_thread)
        self.token_refresh_thread.daemon = True  # Daemonize the thread
        self.token_refresh_thread.start()

        self.kapis_kapis_chat_id = "19:9690c679cc8f438695607727332d3ea0@thread.v2"
        self.notification_group_chat_id = (
            "19:5b795af957f7435e810f0a97a9782c67@thread.v2"
        )
        self.name_to_id_map = self.get_members()

    def refresh_token_thread(self):
        while True:
            self.access_token = get_access_token()
            time.sleep(60 * 31)  # 31 minutes

    def get_members(self):
        wanted_command = (
            f"https://graph.microsoft.com/v1.0/chats/{self.kapis_kapis_chat_id}/members"
        )
        request_headers = {
            "Authorization": "Bearer " + self.access_token,
            "Content-Type": "application/json",
        }
        query_results = requests.get(wanted_command, headers=request_headers).json()

        name_to_id_map = {}
        for person in query_results["value"]:
            name_to_id_map[
                " ".join(person["displayName"].lower().split()).replace("i̇", "i")
            ] = person["userId"]

        return name_to_id_map

    def send_message_to_the_group(self, content, mentioned_people):
        wanted_command = f"https://graph.microsoft.com/v1.0/chats/{self.notification_group_chat_id}/messages"
        request_headers = {
            "Authorization": "Bearer " + self.access_token,
            "Content-Type": "application/json",
        }

        request_body = {"body": {"contentType": "html", "content": content}}
        if mentioned_people:
            request_body["mentions"] = []
            for mention_id, mention_text in mentioned_people.items():
                request_body["mentions"].append(
                    {
                        "id": mention_id,
                        "mentionText": mention_text,
                        "mentioned": {
                            "user": {"id": self.name_to_id_map[mention_text]}
                        },
                    }
                )

        query_results = requests.post(
            wanted_command, headers=request_headers, json=request_body
        ).json()
        # print(json.dumps(queryResults, indent=2))

    def send_warning(self, gpu_id, pid_gpu_memory_list):
        current_time_ = datetime.datetime.now()
        current_time_as_time = current_time_.time()

        shift_start_time = datetime.time(9, 0)
        shift_end_time = datetime.time(21, 0)
        if not (shift_start_time <= current_time_as_time <= shift_end_time):
            return

        current_time = current_time_.strftime("%Y-%m-%d %H:%M:%S")
        message_content = f"<u><b>[{self.machine_name}]</b> Utilization 0% at GPU {gpu_id}, Time: {current_time}</u><br>"
        mentioned_people = {}
        mentioned_person_index = 0

        for pid in pid_gpu_memory_list:
            related_people_str = "Related People:"
            for person_name in pid["people"]:
                related_people_str += (
                    f' <at id="{mentioned_person_index}">{person_name}</at>'
                )
                mentioned_people[mentioned_person_index] = person_name
                mentioned_person_index += 1
            related_people_str += ", "
            if not pid["people"]:
                related_people_str = ""

            message_content += f"- {related_people_str}PID: {pid['pid']}, GPU Memory: {pid['gpu_memory']}, PWD: {pid['pwd']}<br>-- Command: {pid['cmd']}<br><br>"

        self.send_message_to_the_group(message_content, mentioned_people)
