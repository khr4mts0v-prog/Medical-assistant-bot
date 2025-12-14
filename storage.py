import yadisk
import json
import os

yd = yadisk.YaDisk(token=os.environ["YADISK_TOKEN"])

def save_doc(path, meta):
    yd.upload(path, meta["cloud_path"], overwrite=True)
    yd.upload_json(meta["json"], meta["cloud_path"] + ".json", overwrite=True)

def load_all_docs():
    docs = []
    for item in yd.listdir("/"):
        if item["path"].endswith(".json"):
            docs.append(yd.download_json(item["path"]))
    return docs
