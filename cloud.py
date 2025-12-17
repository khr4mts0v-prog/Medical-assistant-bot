import os
import logging
from yadisk import YaDisk
from typing import List

class YaDiskClient:
    def __init__(self, token: str):
        self.yd = YaDisk(token=token)
        logging.info("YaDisk client initialized")

    def folder_exists(self, path: str) -> bool:
        """Проверка, существует ли папка на Яндекс.Диске"""
        try:
            return self.yd.exists(path)
        except Exception as e:
            logging.error(f"folder_exists error: {e}")
            return False

    def create_patient_folder(self, root_folder: str, patient_name: str):
        """Создание папки для пациента, если не существует"""
        try:
            patient_path = f"{root_folder}/{patient_name}"
            docs_path = f"{patient_path}/docs"
            ocr_path = f"{patient_path}/OCR"

            if not self.folder_exists(patient_path):
                self.yd.mkdir(patient_path)
            if not self.folder_exists(docs_path):
                self.yd.mkdir(docs_path)
            if not self.folder_exists(ocr_path):
                self.yd.mkdir(ocr_path)
        except Exception as e:
            logging.error(f"create_patient_folder error: {e}")

    def list_folders(self, root_folder: str) -> List[str]:
        """Список папок (пациентов) в корневой папке"""
        try:
            res = self.yd.listdir(root_folder)
            return [item["name"] for item in res if item["type"] == "dir"]
        except Exception as e:
            logging.error(f"list_folders error: {e}")
            return []

    def list_files(self, path: str) -> List[str]:
        """Список файлов в папке"""
        try:
            res = self.yd.listdir(path)
            return [item["name"] for item in res if item["type"] == "file"]
        except Exception as e:
            logging.error(f"list_files error: {e}")
            return []

    def upload_file(self, local_path: str, remote_path: str):
        """Загрузка файла на Яндекс.Диск"""
        try:
            self.yd.upload(local_path, remote_path, overwrite=True)
        except Exception as e:
            logging.error(f"upload_file error: {e}")

    def upload_text(self, text: str, remote_path: str):
        """Сохранение текстового OCR файла на диск"""
        try:
            with open("/tmp/temp_ocr.txt", "w", encoding="utf-8") as f:
                f.write(text)
            self.upload_file("/tmp/temp_ocr.txt", remote_path)
            os.remove("/tmp/temp_ocr.txt")
        except Exception as e:
            logging.error(f"upload_text error: {e}")

    def download_file(self, remote_path: str, local_path: str):
        """Скачивание файла с Яндекс.Диска"""
        try:
            self.yd.download(remote_path, local_path)
        except Exception as e:
            logging.error(f"download_file error: {e}")

    def search_documents(self, patient_folder: str, keywords: List[str]) -> List[str]:
        """
        Поиск документов по ключевым словам.
        Возвращает список имен файлов, содержащих хотя бы одно ключевое слово в названии.
        """
        result = []
        docs_path = f"{patient_folder}/docs"
        try:
            files = self.list_files(docs_path)
            for f in files:
                if any(k.lower() in f.lower() for k in keywords):
                    result.append(f)
        except Exception as e:
            logging.error(f"search_documents error: {e}")
        return result