import os
import yadisk

YADISK_TOKEN = os.getenv("YANDEX_TOKEN")
y = yadisk.YaDisk(token=YADISK_TOKEN)

def upload_file(file_bytes, path: str):
    if not y.exists(os.path.dirname(path)):
        y.mkdir(os.path.dirname(path))
    y.upload(file_bytes, path, overwrite=True)
