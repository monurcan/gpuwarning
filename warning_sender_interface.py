from abc import ABC, abstractmethod


class WarningSender(ABC):
    def __init__(self, machine_name):
        self.machine_name = machine_name

    @abstractmethod
    def send_warning(self, gpu_id, pid_gpu_memory_list):
        pass
