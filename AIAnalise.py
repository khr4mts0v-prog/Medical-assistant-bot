import requests
import logging
from typing import List
import re

# ----------------------
# Настройки
# ----------------------
HF_API_TOKEN = None  # В main.py будем передавать токен при вызове функций

# ----------------------
# Классификация документа
# ----------------------
def classify_document(text: str, hf_token: str) -> str:
    """
    Определяет тип документа по его тексту.
    Возвращает строку с классификацией.
    """
    global HF_API_TOKEN
    HF_API_TOKEN = hf_token

    # Расширенный список возможных типов
    types = [
        "ЭКГ", "ЭЭГ", "УЗИ", "МРТ", "КТ", "Рентген",
        "Анализы крови", "Анализы мочи", "Анализы кала",
        "Консультация офтальмолога", "Консультация ЛОР",
        "Консультация терапевта", "Консультация кардиолога",
        "Консультация эндокринолога", "Консультация невролога",
        "Консультация хирурга", "Консультация педиатра",
        "Вакцинация", "Прививка", "Флюорография",
        "Диетолог", "Физиотерапия", "Сонограмма",
        "Заключение"
    ]

    # Локальная проверка по ключевым словам
    for t in types:
        if t.lower() in text.lower():
            return t

    # Если не нашли — попробуем через нейросеть
    try:
        url = "https://router.huggingface.co/models/google/flan-t5-small"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        prompt = f"Определи тип медицинского документа по тексту: {text[:500]}"
        payload = {"inputs": prompt}
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        res_json = resp.json()
        if isinstance(res_json, list) and res_json:
            return res_json[0].get("generated_text", "Неопределено")
    except Exception as e:
        logging.error(f"Error classify_document: {e}")

    return "Неопределено"


# ----------------------
# Извлечение ключевых слов
# ----------------------
def extract_keywords(text: str, max_words: int = 10) -> List[str]:
    """
    Простое извлечение ключевых слов: самые часто встречающиеся слова,
    кроме стоп-слов.
    """
    stop_words = set([
        "и", "в", "на", "с", "по", "от", "за", "не", "на", "для", "к",
        "с", "что", "это", "так", "как", "а", "но", "или", "по", "когда"
    ])
    words = re.findall(r'\b\w+\b', text.lower())
    freq = {}
    for w in words:
        if w not in stop_words and len(w) > 2:
            freq[w] = freq.get(w, 0) + 1
    # Сортируем по частоте
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:max_words]]


# ----------------------
# Ответ на вопрос пользователя
# ----------------------
def answer_question(texts: List[str], question: str, hf_token: str) -> str:
    """
    Получаем список OCR-текстов документов и вопрос пользователя,
    отправляем в HF модель, получаем ответ.
    """
    global HF_API_TOKEN
    HF_API_TOKEN = hf_token
    try:
        combined_text = "\n".join(texts[:5])  # берем первые 5 документов
        prompt = f"Документы:\n{combined_text}\nВопрос: {question}\nОтветь кратко и по делу."
        url = "https://router.huggingface.co/models/google/flan-t5-small"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        payload = {"inputs": prompt}
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        res_json = resp.json()
        if isinstance(res_json, list) and res_json:
            return res_json[0].get("generated_text", "Ошибка генерации")
    except Exception as e:
        logging.error(f"Error answer_question: {e}")
    return "Ошибка генерации"