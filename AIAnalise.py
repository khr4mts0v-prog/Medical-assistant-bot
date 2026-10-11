import os
import requests

TYPES = {
    "анализы": ["анализ крови", "гемоглобин", "ферритин", "лаборатор"],
    "УЗИ": ["узи", "ультразвуков"], "ЭКГ": ["экг", "электрокардиограмм"],
    "МРТ": ["мрт"], "КТ": ["компьютерная томограф"],
    "рентген": ["рентген"], "выписка": ["эпикриз", "выписка"],
    "назначение": ["назначено", "рекомендовано", "дозировка"],
}
def classify_document(text, hf_token=None):
    text = (text or "").lower()
    return max(TYPES, key=lambda k: sum(w in text for w in TYPES[k])) if any(w in text for ws in TYPES.values() for w in ws) else "документ"

def extract_keywords(text):
    stop = {"этот", "того", "при", "для", "или", "что"}
    return list(dict.fromkeys(w.strip(".,:;()") for w in text.lower().split() if len(w.strip(".,:;()")) > 4 and w.strip(".,:;()") not in stop))[:8]

def answer_question(query, patient, hf_token, context=""):
    if not context:
        return "В архиве нет подходящих документов. Сначала загрузите документы пациента."
    if not hf_token:
        return "Не задан HF_API_TOKEN. Поиск работает, но ИИ не настроен."
    system = ("Ты медицинский аналитик. Отвечай по-русски. Разделяй факты из документов и гипотезы; "
              "не выдумывай диагнозы, даты или назначения. Указывай названия источников. "
              "Обсуждая лечение, предложи вопросы лечащему врачу, не назначай и не отменяй лечение. "
              "Если данных недостаточно, скажи об этом.")
    model = os.getenv("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    url = os.getenv("HF_CHAT_COMPLETIONS_URL", "https://router.huggingface.co/v1/chat/completions")
    try:
        response = requests.post(url, headers={"Authorization": f"Bearer {hf_token}"}, json={
            "model": model, "messages": [
                {"role":"system","content":system},
                {"role":"user","content":f"Вопрос: {query}\nДокументы из выбранного семейного архива:\n{context[:18000]}"}
            ], "temperature":0.2, "max_tokens":1200
        }, timeout=90)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Не удалось получить ответ ИИ ({type(e).__name__}: {e}). Проверьте токен и модель."
