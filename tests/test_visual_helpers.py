import webapp


def test_document_count_uses_russian_plural_forms():
    assert [webapp.format_document_count(n) for n in (0, 1, 2, 3, 4, 5, 11, 14, 21, 22, 25, 101, 114)] == [
        "0 документов", "1 документ", "2 документа", "3 документа", "4 документа",
        "5 документов", "11 документов", "14 документов", "21 документ",
        "22 документа", "25 документов", "101 документ", "114 документов",
    ]


def test_document_dates_are_displayed_with_dots():
    assert webapp.format_document_date("15-10-2026") == "15.10.2026"
    assert webapp.format_document_date("5/2/2025") == "05.02.2025"
    assert webapp.format_document_date("Дата не указана") == "Дата не указана"


def test_document_card_metadata_uses_explicit_ocr_fields_and_conclusion():
    document = {"text": "Клиника: Медцентр Север\nВрач: Иванов И.И.\nЗаключение: без острой патологии"}
    result = webapp.document_card_metadata(document, {})
    assert result["doctor"] == "Иванов И.И."
    assert result["clinic"] == "Медцентр Север"
    assert result["finding"] == "без острой патологии"
    assert "Врач: Иванов И.И." in result["metadata"]


def test_document_card_metadata_does_not_invent_missing_conclusion():
    result = webapp.document_card_metadata({"text": "Только технический текст"}, {})
    assert result["doctor"] == ""
    assert result["clinic"] == ""
    assert result["finding"] == ""
