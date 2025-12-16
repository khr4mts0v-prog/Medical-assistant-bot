import requests
import re
from dateutil import parser
from rapidfuzz import fuzz

HF_URL = "https://router.huggingface.co/hf-inference/models/google/flan-t5-base"

class AI:
    def __init__(self, token):
        self.headers = {
            "Authorization": f"Bearer {token}"
        }

    def _ask(self, prompt: str) -> str:
        r = requests.post(
            HF_URL,
            headers=self.headers,
            json={"inputs": prompt},
            timeout=60
        )
        if r.status_code != 200:
            return ""
        return r.json()[0]["generated_text"]

    def classify_document(self, text: str):
        prompt = f"""
Определи тип медицинского документа (одно слово),
дату исследования (дд-мм-гггг),
и 5 ключевых медицинских слов.

Текст:
{text[:2000]}
"""
        answer = self._ask(prompt)

        doc_type = "Документ"
        date = None
        keywords = []

        if answer:
            lines = answer.lower().splitlines()
            for l in lines:
                if "узи" in l:
                    doc_type = "УЗИ"
                if "экг" in l:
                    doc_type = "ЭКГ"
                if "мрт" in l:
                    doc_type = "МРТ"

                if not date:
                    try:
                        date = parser.parse(l, dayfirst=True).strftime("%d-%m-%Y")
                    except:
                        pass

                if len(keywords) < 5:
                    words = re.findall(r"[а-яё]{4,}", l)
                    keywords.extend(words)

        return {
            "type": doc_type,
            "date": date,
            "keywords": list(set(keywords))[:5]
        }

    def answer_question(self, question: str, texts: list[str]) -> str:
        joined = "\n\n".join(texts[:5])
        prompt = f"""
Вопрос: {question}

Медицинские данные:
{joined}

Дай краткий и понятный ответ.
"""
        return self._ask(prompt)