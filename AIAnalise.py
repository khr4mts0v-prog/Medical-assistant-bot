import requests
import logging
import os
from dotenv import load_dotenv
load_dotenv()
HF_API_TOKEN = os.getenv("HF_API_TOKEN")

def get_embedding(text):
    url = "https://router.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error(f"HF embedding error: {e}")
        return []

def hf_text_gen(text):
    url = "https://router.huggingface.co/models/EleutherAI/gpt-neo-125M"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and len(result) > 0:
            return result[0].get("generated_text", "Ошибка генерации")
        return "Ошибка генерации"
    except Exception as e:
        logging.error(f"HF text gen error: {e}")
        return "Ошибка генерации"
