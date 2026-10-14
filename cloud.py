import logging
from yadisk import YaDisk

class YaDiskClient:
    def __init__(self, token):
        if not token: raise ValueError("Yandex Disk OAuth token is missing")
        self.yd=YaDisk(token=token)

    def ensure_folder(self,path):
        parts,current=path.strip("/").split("/"),""
        for part in parts:
            current=f"{current}/{part}".strip("/")
            if not self.yd.exists(current):
                try: self.yd.mkdir(current)
                except Exception:
                    if not self.yd.exists(current):
                        logging.exception("Cannot create Yandex Disk folder")
                        raise

    def upload_file(self,local,remote):
        self.yd.upload(local,remote,overwrite=True)

    def list_folder(self,path):
        return list(self.yd.listdir(path))

    def download_file(self,remote,local):
        self.yd.download(remote,local)

    def delete_file(self, remote, permanently=True):
        """Delete a file from Yandex Disk; propagate errors to caller."""
        if not remote:
            return False
        if self.yd.exists(remote):
            self.yd.remove(remote, permanently=permanently)
            return True
        return False
