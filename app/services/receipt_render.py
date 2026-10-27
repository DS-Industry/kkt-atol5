"""Readable receipt image from a persisted ATOL getFnDocument response.

Numeric TLV tags remain the source of truth. Missing fields are never invented.
Registration/cliche context is stored separately at the time the document is read.
"""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlencode

from PIL import Image, ImageDraw

LABELS = {
    '1008': 'Контакт покупателя', '1009': 'Адрес', '1012': 'Дата и время',
    '1013': 'ЗН ККТ', '1018': 'ИНН', '1020': 'ИТОГО', '1021': 'Кассир',
    '1031': 'Наличными', '1036': '№ автомата', '1037': 'РН ККТ',
    '1038': 'Смена №', '1040': 'ФД', '1041': 'ФН', '1042': 'Чек №',
    '1048': 'Организация', '1054': 'Признак расчёта', '1055': 'СНО',
    '1060': 'Сайт ФНС', '1077': 'ФП (исходный TLV)', '1081': 'Безналичными',
    '1102': 'Сумма НДС (тег 1102)', '1103': 'Сумма НДС 10%',
    '1104': 'Сумма с НДС 0%', '1105': 'Сумма без НДС',
    '1106': 'Сумма расчётного НДС (тег 1106)', '1107': 'Сумма НДС 10/110',
    '1117': 'Эл. адрес отправителя', '1187': 'Место расчётов',
    '1188': 'Версия ККТ', '1192': 'Дополнительный реквизит',
    '1203': 'ИНН кассира', '1209': 'Версия ФФД',
    '1215': 'Предоплатой (зачёт аванса)', '1216': 'Постоплатой (в кредит)',
    '1217': 'Встречным предоставлением',
    '1023': 'Количество', '1030': 'Наименование', '1043': 'Стоимость',
    '1079': 'Цена', '1199': 'Ставка НДС', '1200': 'Сумма НДС',
    '1212': 'Предмет расчёта', '1214': 'Способ расчёта',
}
SNO = {1: 'ОСН', 2: 'УСН доход', 4: 'УСН доход − расход',
       8: 'ЕНВД', 16: 'ЕСХН', 32: 'Патент'}
VAT = {1: 'НДС (код ставки 1)', 2: 'НДС 10%', 3: 'Расчётный НДС (код ставки 3)', 4: 'НДС 10/110',
       5: 'НДС 0%', 6: 'Без НДС', 7: 'НДС 5%', 8: 'НДС 7%',
       9: 'НДС 5/105', 10: 'НДС 7/107'}
METHOD = {1: 'Предоплата 100%', 2: 'Предоплата', 3: 'Аванс',
          4: 'Полный расчёт', 5: 'Частичный расчёт и кредит',
          6: 'Передача в кредит', 7: 'Оплата кредита'}
SUBJECT = {1: 'Товар', 2: 'Подакцизный товар', 3: 'Работа', 4: 'Услуга',
           10: 'Платёж', 11: 'Агентское вознаграждение', 12: 'Составной предмет расчёта',
           13: 'Иной предмет расчёта'}
MONEY_TAGS = {'1020','1031','1081','1102','1103','1104','1105','1106','1107',
              '1215','1216','1217','1043','1079','1200'}


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        return f'{amount:,.2f}'.replace(',', ' ').replace('.', ',')
    except (InvalidOperation, ValueError):
        return str(value)


def ofd_receipt_url(qr, base="https://consumer.1-ofd.ru/v1?"):
    """Build the public First OFD receipt URL from the mandatory fiscal QR.

    The stored QR remains untouched for audit/FNS verification. This URL is
    only used as the human-facing QR printed inside the receipt image.
    """
    fields = parse_qs(str(qr or ""), keep_blank_values=True)
    required = ("fn", "fp", "i", "t", "s", "n")
    values = {key: fields[key][0] for key in required if fields.get(key)}
    if len(values) != len(required):
        raise ValueError("Fiscal QR lacks fields required for OFD link")
    return base + urlencode(values)


def value_label(tag, value):
    if tag in MONEY_TAGS:
        return money(value)
    mapping = {'1055': SNO, '1199': VAT, '1212': SUBJECT, '1214': METHOD,
               '1209': {1: '1.0', 2: '1.05', 3: '1.1', 4: '1.2'}}.get(tag)
    if mapping:
        return mapping.get(value, str(value))
    if tag == '1012':
        try:
            return datetime.fromisoformat(value).strftime('%d.%m.%Y %H:%M:%S')
        except (ValueError, TypeError):
            pass
    return str(value)


def receipt_lines(payload, qr):
    """Return (text, size, bold) rows; every fiscal TLV field is represented."""
    document = json.loads(payload) if isinstance(payload, str) else payload
    tlv = document.get('documentTLV', {})
    if not isinstance(tlv, dict) or tlv.get('qr') != qr:
        raise ValueError('Fiscal document does not match receipt QR')
    context = document.get('receiptContext') or {}
    # Context may only fill cliche/identity values, never money, cashier or items.
    for tag in ('1018', '1037'):
        if context.get(tag) and tlv.get(tag) and context[tag] != tlv[tag]:
            context = {}
            break
    lines = []
    used = {'qr', 'short', 'fiscalDocumentType', '1059'}
    def add(text, size=24, bold=False):
        lines.append((str(text), size, bold))
    def field(tag, allow_context=False, size=24, bold=False):
        value = tlv.get(tag)
        if value is None and allow_context:
            value = context.get(tag)
        used.add(tag)
        if value is not None and str(value).strip():
            add(f'{LABELS.get(tag, "Тег " + tag)}: {value_label(tag, value)}', size, bold)
    for tag in ('1048','1018','1009','1187'):
        field(tag, True, 26 if tag == '1048' else 22, tag == '1048')
    add('КАССОВЫЙ ЧЕК', 32, True)
    add({1:'ПРИХОД',2:'ВОЗВРАТ ПРИХОДА',3:'РАСХОД',4:'ВОЗВРАТ РАСХОДА'}.get(
        tlv.get('1054'), 'Признак расчёта: '+str(tlv.get('1054','не указан'))), 28, True)
    used.add('1054')
    for tag in ('1012','1042','1038','1055'):
        field(tag)
    if tlv.get('short'):
        add('ФН вернул сокращённый документ; часть реквизитов недоступна.',22)
    add('─' * 32)
    items = tlv.get('1059', [])
    if isinstance(items, dict):
        items = [items]
    for number, item in enumerate(items, 1):
        add(f'{number}. {item.get("1030", "Позиция")}',26,True)
        for tag in ('1023','1079','1043','1199','1200','1212','1214'):
            if tag in item:
                add(f'{LABELS[tag]}: {value_label(tag,item[tag])}')
        for tag, value in item.items():
            if tag not in {'1030','1023','1079','1043','1199','1200','1212','1214'}:
                extra(tag, value, add)
        add('─' * 32)
    field('1020',size=34,bold=True)
    for tag in ('1031','1081','1215','1216','1217','1102','1103','1104','1105','1106','1107'):
        field(tag)
    add('─' * 32)
    for tag in ('1021','1203','1041','1040','1037','1013','1036','1209','1060','1117','1008'):
        field(tag, tag in {'1037','1013','1060','1117'})
    # ATOL returns 1077 as a six-byte hex value; the fiscal QR supplies its
    # printable decimal form. Do not decimal-parse the six-byte TLV wholesale.
    fp = parse_qs(qr).get('fp',[None])[0]
    if fp:
        add('ФПД: '+fp)
        used.add('1077')
    for tag,value in tlv.items():
        if tag not in used:
            extra(tag,value,add)
    if document.get('receiptContextHistorical') and context:
        add('Реквизиты организации дополнены по данным ККТ на момент восстановления изображения.',18)
    return lines


def extra(tag, value, add):
    label = LABELS.get(tag, 'Тег '+tag)
    if isinstance(value, dict):
        add(label+':',22)
        for key, child in value.items():
            extra(key,child,add)
    elif isinstance(value,list):
        add(label+':',22)
        for child in value:
            if isinstance(child,dict):
                for key,v in child.items(): extra(key,v,add)
            else: add(str(child),22)
    else:
        add(label+': '+value_label(tag,value),22)


def receipt_image(payload, qr, qr_image, font, wrap):
    qr_image = qr_image.convert('RGB')
    width, margin = max(680,qr_image.width+64), 32
    prepared, y = [], margin
    for text,size,bold in receipt_lines(payload,qr):
        face = font(size,bold)
        for line in wrap(text,face,width-2*margin):
            prepared.append((line,face,y))
            y += size+8
        y += 5
    qr_top = y+20
    canvas = Image.new('RGB',(width,qr_top+qr_image.height+70),'white')
    draw = ImageDraw.Draw(canvas)
    for line,face,top in prepared:
        draw.text((margin,top),line,font=face,fill='black')
    canvas.paste(qr_image,((width-qr_image.width)//2,qr_top))
    draw.text((margin,qr_top+qr_image.height+12),'Данные фискального документа из ФН',font=font(20),fill='black')
    return canvas
