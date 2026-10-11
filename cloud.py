import logging
from yadisk import YaDisk

class YaDiskClient:
    def __init__(self, token):
        if not token:
            raise ValueError("Set YADISK_TOKEN in .env")
        self.yd = YaDisk(token=token)

    def ensure_folder(self, path):
        parts, current = path.strip("/").split("/"), ""
        for part in parts:
            current = f"{current}/{part}".strip("/")
            if not self.yd.exists(current):
                try:
                    self.yd.mkdir(current)
                except Exception:
                    if not self.yd.exists(current):
                        logging.exception("Cannot create %s", current)
                        raise

    def upload_file(self, local, remote):
        try:
            self.yd.upload(local, remote, overwrite=True)
        except Exception:
            logging.exception("Upload failed: %s", remote)
            raise

    def list_folder(self, path):
        return list(self.yd.listdir(path))

    def download_file(self, remote, local):
        self.yd.download(remote, local)
