from yadisk import YaDisk

class YaDiskClient:
    def __init__(self, token):
        self.yd = YaDisk(token=token)

    def upload_file(self, local_path, remote_path):
        folder = "/".join(remote_path.split("/")[:-1])
        if not self.yd.exists(folder):
            self.yd.mkdir(folder)
        self.yd.upload(local_path, remote_path, overwrite=True)

    def list_files(self, remote_folder):
        if not self.yd.exists(remote_folder):
            return []
        return [f["name"] for f in self.yd.listdir(remote_folder)]