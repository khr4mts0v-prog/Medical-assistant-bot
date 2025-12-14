import os
import requests

HF_TOKEN = os.environ["HF_API_TOKEN"]

def get_embedding(text: str) -> list:
    r = requests.post(
        "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        json={"inputs": text[:2000]}
    )
    return r.json()[0]
