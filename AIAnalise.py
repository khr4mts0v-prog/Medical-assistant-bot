import logging
import requests

# ----------------------
# Классификация документа
# ----------------------
def classify_document(text: str, hf_token: str) -> str:
    """
    Определяет тип документа (УЗИ, ЭКГ, анализы, консультации и т.д.)
    """
    # Расширенный список типов документов
    doc_types = [
        "УЗИ", "ЭКГ", "анализы", "консультация офтальмолога", "консультация ЛОРа",
        "рентген", "КТ", "МРТ", "лабораторное исследование", "визит к терапевту",
        "визит к кардиологу", "визит к неврологу", "вакцинация", "скрининг",
    ]
    # Запрос к нейросети для классификации
    url = "https://api-inference.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2"
    headers = {"Authorization": f"Bearer {hf_token}"}
    try:
        # Берём первые несколько слов для сопоставления с типом документа
        for dtype in doc_types:
            if dtype.lower() in text.lower():
                logging.info(f"Классификация документа определена как: {dtype}")
                return dtype
        logging.info("Классификация документа: неизвестно, присвоено 'документ'")
        return "документ"
    except Exception as e:
        logging.error(f"Ошибка классификации документа: {e}")
        return "документ"

# ----------------------
# Извлечение ключевых слов
# ----------------------
def extract_keywords(text: str) -> list:
    """
    Простое извлечение ключевых слов: первые 7 слов
    """
    words = [w.strip(",.!?") for w in text.split()]
    keywords = list(dict.fromkeys(words))[:7]
    logging.info(f"Ключевые слова извлечены: {keywords}")
    return keywords

# ----------------------
# Ответ на пользовательский запрос
# ----------------------
def answer_question(query: str, patient: str, hf_token: str) -> str:
    """
    Отправляет запрос к нейросети и возвращает ответ
    """
    url = "https://api-inference.huggingface.co/models/gpt2"
    headers = {"Authorization": f"Bearer {hf_token}"}
    payload = {"inputs": query}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and "generated_text" in result[0]:
            return result[0]["generated_text"]
        return str(result)
    except Exception as e:
        logging.error(f"Ошибка генерации ответа нейросетью: {e}")
        return "Ошибка генерации"