import os
import json
import logging
from yadisk import YaDisk

class YandexDiskClient:
    def __init__(self, token, root_folder="MedBot"):
        self.yd = YaDisk(token=token)
        self.root_folder = root_folder
        if not self.yd.exists(root_folder):
            self.yd.mkdir(root_folder)

    def list_patients(self):
        """Возвращает список папок (пациентов)"""
        patients = []
        try:
            for item in self.yd.listdir(self.root_folder):
                if item["type"] == "dir":
                    patients.append(item["name"])
        except Exception as e:
            logging.error(f"Ошибка получения списка пациентов: {e}")
        return patients

    def upload_file(self, local_path, patient, file_name):
        folder_path = f"{self.root_folder}/{patient}"
        if not self.yd.exists(folder_path):
            self.yd.mkdir(folder_path)
        remote_path = f"{folder_path}/{file_name}"
        self.yd.upload(local_path, remote_path, overwrite=True)
        return remote_path

    def load_json(self, file_name="patients_data.json"):
        local_tmp = f"/tmp/{file_name}"
        remote_path = f"{self.root_folder}/{file_name}"
        try:
            if self.yd.exists(remote_path):
                self.yd.download(remote_path, local_tmp)
                with open(local_tmp, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"JSON не найден или ошибка: {e}")
        return {}

    def save_json(self, data, file_name="patients_data.json"):
        local_tmp = f"/tmp/{file_name}"
        with open(local_tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        remote_path = f"{self.root_folder}/{file_name}"
        self.yd.upload(local_tmp, remote_path, overwrite=True)