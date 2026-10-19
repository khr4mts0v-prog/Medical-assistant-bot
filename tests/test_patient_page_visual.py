from unittest.mock import patch

import webapp


def test_patient_page_uses_two_by_two_actions_and_ai_primary():
    with patch("webapp.family"), patch("webapp.db.patients", return_value=["Александр Иванов"]), \
         patch("webapp.db.search", return_value=[]), patch("webapp.is_demo_user", return_value=False), \
         patch("webapp.STORAGE_BACKEND", "local"):
        response = webapp.patient_page(1, "Александр Иванов", uid=7)
    body = response.body.decode()
    assert 'class="patient-actions"' in body
    assert 'class="button-link patient-action-primary"' in body
    assert 'Спросить ИИ</a>' in body
    assert '✎ Редактировать' not in body
    assert 'Редактировать</a>' in body
    assert '.patient-actions{display:grid' in body


def test_document_card_hides_source_filename_until_expanded_and_formats_date():
    row = {
        "id": 41, "patient": "Александр Иванов", "name": "Alex_7c1b1640.png",
        "kind": "заключение УЗИ", "date": "15-10-2026",
        "text": "Врач: Иванов И.И.\\nЗаключение: без острой патологии",
        "analysis": {"display_title": "УЗИ щитовидной железы"},
    }
    with patch("webapp.family"), patch("webapp.db.patients", return_value=["Александр Иванов"]), \
         patch("webapp.db.search", return_value=[row]), patch("webapp.is_demo_user", return_value=False), \
         patch("webapp.STORAGE_BACKEND", "local"):
        response = webapp.patient_page(1, "Александр Иванов", uid=7)
    body = response.body.decode()
    assert "УЗИ щитовидной железы" in body
    assert "15.10.2026" in body
    assert "Врач: Иванов И.И." in body
    assert '<details class="document-source-name"><summary>Имя исходного файла</summary><span>Alex_7c1b1640.png</span></details>' in body
    assert body.index('<details class="document-source-name">') < body.index("Alex_7c1b1640.png")
    assert 'Alex_7c1b1640.png</strong>' not in body