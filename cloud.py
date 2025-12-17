import logging
from yadisk import YaDisk

class YaDiskClient:
    def __init__(self, token: str):
        self.yd = YaDisk(token=token)

    def ensure_folder(self, path: str):
        """Создаёт папку, если её нет"""
        try:
            if not self.yd.exists(path):
                self.yd.mkdir(path)
                logging.info(f"Папка создана на Яндекс.Диске: {path}")
        except Exception as e:
            logging.error(f"Ошибка создания папки {path}: {e}")

    def upload_file(self, local_path: str, remote_path: str):
        """Загружает файл на Яндекс.Диск"""
        try:
            self.yd.upload(local_path, remote_path, overwrite=True)
            logging.info(f"Файл {local_path} загружен как {remote_path}")
        except Exception as e:
            logging.error(f"Ошибка загрузки файла {local_path}: {e}")

    def list_folder(self, remote_path: str):
        """Список файлов в папке"""
        try:
            files = self.yd.listdir(remote_path)
            return [f['name'] for f in files if f['type'] == 'file']
        except Exception as e:
            logging.error(f"Ошибка получения списка папки {remote_path}: {e}")
            return []

    def download_file(self, remote_path: str, local_path: str):
        """Скачивает файл с диска"""
        try:
            self.yd.download(remote_path, local_path)
            logging.info(f"Файл {remote_path} скачан в {local_path}")
        except Exception as e:
            logging.error(f"Ошибка скачивания файла {remote_path}: {e}")