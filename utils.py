import re
import datetime

# ----------------------
# Форматирование имени файла
# ----------------------
def format_filename(patient_name: str, doc_type: str, date_str: str, extension: str) -> str:
    """
    Формирует имя файла в формате:
    <имя пациента>_<тип документа>_<дата>.<расширение>
    """
    safe_patient = re.sub(r'\W+', '_', patient_name.strip())
    safe_type = re.sub(r'\W+', '_', doc_type.strip())
    safe_date = re.sub(r'\W+', '-', date_str.strip())
    return f"{safe_patient}_{safe_type}_{safe_date}.{extension}"

# ----------------------
# Извлечение даты из текста
# ----------------------
def parse_date_from_text(text: str) -> str:
    """
    Пытается найти дату в тексте в формате дд-мм-гггг или похожем.
    Если не находит — возвращает сегодняшнюю дату.
    """
    date_patterns = [
        r'(\d{2})[.\-/](\d{2})[.\-/](\d{4})',  # 17-03-2025, 17.03.2025
        r'(\d{2})[.\-/](\d{2})[.\-/](\d{2})',  # 17-03-25
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            day, month, year = match.groups()
            if len(year) == 2:
                year = "20" + year
            try:
                date_obj = datetime.date(int(year), int(month), int(day))
                return date_obj.strftime("%d-%m-%Y")
            except ValueError:
                continue
    # Если не нашли, возвращаем текущую дату
    return datetime.date.today().strftime("%d-%m-%Y")