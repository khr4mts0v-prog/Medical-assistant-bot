import os
from huggingface_hub import InferenceClient

HF_API_TOKEN = os.getenv("HF_API_TOKEN")
hf_client = InferenceClient(HF_API_TOKEN)

def get_embedding(text: str):
    result = hf_client.text_features(model="sentence-transformers/all-MiniLM-L6-v2", inputs=text)
    return result
