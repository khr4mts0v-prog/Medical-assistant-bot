import requests
import os
import logging

YADISK_API = "https://cloud-api.yandex.net/v1/disk/resources"

class YaDisk:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"OAuth {token}"
        }

    def ensure_dir(self, path: str):
        r = requests.put(
            YADISK_API,
            headers=self.headers,
            params={"path": path}
        )
        if r.status_code not in (201, 409):
            logging.error(f"YaDisk mkdir error {path}: {r.text}")

    def upload_file(self, local_path: str, yadisk_path: str):
        get_url = requests.get(
            f"{YADISK_API}/upload",
            headers=self.headers,
            params={"path": yadisk_path, "overwrite": True}
        ).json()

        with open(local_path, "rb") as f:
            r = requests.put(get_url["href"], files={"file": f})
            if r.status_code not in (201, 202):
                logging.error(f"Upload failed {yadisk_path}")

    def download_file(self, yadisk_path: str, local_path: str):
        get_url = requests.get(
            f"{YADISK_API}/download",
            headers=self.headers,
            params={"path": yadisk_path}
        ).json()

        r = requests.get(get_url["href"])
        with open(local_path, "wb") as f:
            f.write(r.content)

    def list_dir(self, path: str):
        r = requests.get(
            YADISK_API,
            headers=self.headers,
            params={"path": path, "limit": 1000}
        )
        if r.status_code != 200:
            return []
        return r.json().get("_embedded", {}).get("items", [])