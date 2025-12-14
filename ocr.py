import os
import requests

HF_API_TOKEN = os.getenv("HF_API_TOKEN")
HF_MODEL = "microsoft/trocr-base-printed"
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"}

def ocr_image(image_bytes: bytes) -> str:
    response = requests.post(HF_API_URL, headers=HEADERS, data=image_bytes, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"OCR HF error {response.status_code}: {response.text}")

    result = response.json()
    if isinstance(result, list) and "generated_text" in result[0]:
        return result[0]["generated_text"]
    if isinstance(result, dict) and "generated_text" in result:
        return result["generated_text"]
    return ""