# Public medical form classification fixtures

Corpus captured on 2026-10-13 for regression testing of AIAnalise.py.
The fixtures are text extracted from openly available blank forms, official
form descriptions, and public legal reference pages. No family archive data
is included. There are no completed patient records in this fixture directory.

## Source inventory

| Fixture | Expected class | Public source | Notes |
|---|---|---|---|
| discharge_blank.txt | выписной эпикриз | https://4ortopeda.ru/blanki/vipiska.pdf | Blank PDF template |
| form_025_current.txt | медицинская карта или наблюдение | https://www.consultant.ru/document/cons_doc_LAW_506684/62cd22edab99270d377567e73ab7e4664f86bc13/ | Current outpatient form under order 274н (2025) |
| form_027_extract.txt | выписка из медицинской карты | https://base.garant.ru/4172765/ | Legacy form 027/у |
| form_063_vaccine.txt | вакцинальный документ | https://readydoc.ru/obrazec/Karta/Karta_profilakticheskix_privivok_Forma_N_063u | Public template page; legacy form 063/у |
| form_070_sanatorium_referral.txt | санаторно-курортная документация | https://www.consultant.ru/document/cons_doc_LAW_506684/8e19a7568d6caa3632c6f0a1b6cd7d72e7ffbe44/ | Current form 070/у under order 274н |
| form_072_sanatorium_card.txt | санаторно-курортная документация | https://www.consultant.ru/document/cons_doc_LAW_506684/cc080244c37ea24edb016a968bb6683f579b4f4a/ | Current form 072/у under order 274н |
| form_076_child_sanatorium_card.txt | санаторно-курортная документация | https://www.consultant.ru/document/cons_doc_LAW_506684/906c50804f3c02331661b4eefbee006842618871/ | Current form 076/у under order 274н |
| form_079_child_certificate.txt | медицинская справка | https://www.consultant.ru/document/cons_doc_LAW_506684/1c849e3982e118c1af6a73ad6a4fa56e79fbbb8d/ | Current form 079/у under order 274н |
| birth_certificate_103u.txt | медицинское свидетельство о рождении | https://www.consultant.ru/document/cons_doc_LAW_401508/1136520dc7565521987d568901a318b246b94a37/ | Form 103/у, order 987н |
| death_certificate_106u.txt | медицинское свидетельство о смерти | https://www.consultant.ru/document/cons_doc_LAW_385398/47a64dbb8b30494400ba366bcf835bc556660d16/ | Form 106/у, order 352н |
| prescription_148-1u.txt | назначение или рецепт | https://www.consultant.ru/document/cons_doc_LAW_401865/ac42eb2ca47a2eafe8400828c5602fac413c61cf/ | Prescription form 148-1/у-88 |
| disability_certificate_095.txt | справка о временной нетрудоспособности | https://www.consultant.ru/document/cons_doc_LAW_54990/c4cb786e34f6707016ea09394d84a780b031d2fe/ | Legacy form 095/с-у |
| form_086_certificate.txt | медицинская справка | https://www.consultant.ru/document/cons_doc_LAW_175963/999589943642b454003464340e56b0288c788373/ | Older form 086/у; current status not asserted |
| form_030_dispensary.txt | контрольная карта диспансерного наблюдения | https://www.consultant.ru/document/cons_doc_LAW_175963/fb9d7b5b9169bc64ea8895d26a04f643dc9fad03/ | Form 030/у; status should be checked before operational use |
| form_088_mse_referral.txt | направление | https://www.consultant.ru/document/cons_doc_LAW_66771/6087b76effd3d483f5fc5ddf4194f06a068b108e/ | Legacy form 088/у-06 |
| form_088_current.txt | направление | https://base.garant.ru/405685943/ | Form 088/у under joint order 488н/551н (2022) |
| form_112_child_history.txt | история развития ребёнка | https://base.garant.ru/4174100/ | Legacy form 112/у |
| operation_protocol.txt | операционный протокол | https://www.consultant.ru/document/cons_doc_LAW_367763/71fcce1b862d0c42050301716f83e77b33f76802/ | Protocol template |
| pregnancy_exchange_113.txt | документ по беременности и родам | https://www.consultant.ru/document/cons_doc_LAW_367763/60fb65927939bed439385f17334543a387746b54/ | Public form within order 1130н |
| prescription_107-1u.txt | назначение или рецепт | https://www.consultant.ru/document/cons_doc_LAW_401865/af42dc5917c97680f33eaf2d8c74214b0e285cb6/ | Prescription form 107-1/у |
| radiology_protocol.txt | рентгенологическое заключение | https://www.consultant.ru/document/cons_doc_LAW_362387/dfe24e0d5f871d9dde05d247691e7b0a6c93fb90/ | X-ray protocol form |
| referral_057.txt | направление | https://www.consultant.ru/document/cons_doc_LAW_393975/73a6f28a693ee8584cc7c697e4e4fb933cc8c842/ | Form 057/у-04 |
| ultrasound_protocol.txt | заключение УЗИ | https://www.consultant.ru/document/cons_doc_LAW_362485/b51d9dd28d5f66e7566e9524da66c905a4188d85/ | Ultrasound protocol form |

The extraction of some legal-reference pages contains surrounding navigation text,
not only the blank form. This is intentional: it tests whether a clear document
title wins over incidental mentions elsewhere on the page. Legacy forms are
retained to support importing older archives; their presence does not imply they
remain valid for issuing new documents.
