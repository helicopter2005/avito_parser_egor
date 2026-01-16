import re
from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter


def extract_price_per_m2(price_info: str):
    if not price_info:
        return None
    match = re.search(r'([\d\s]+)\s*₽', price_info)
    if match:
        return int(match.group(1).replace(" ", ""))
    return None


def build_excel(data_rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Оценка"

    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    align = Alignment(vertical="bottom", wrap_text=True)
    bold = Font(bold=True)

    headers = [
        "№",
        "Адрес",
        "Цена",
        "Площадь",
        "Цена за м²",
        "Этаж",
        "Площадь участка",
        "Материал стен",
        "Год постройки",
        "Ссылка",
        "Описание",
        "Статус аналога"
    ]

    ws.append(headers)
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.border = border
        cell.font = bold
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # --- ОСНОВНАЯ ТАБЛИЦА ---
    for idx, row in enumerate(data_rows, start=1):
        data = row["data"]
        is_analog = row["is_analog"]

        price_per_m2 = extract_price_per_m2(data.get("price_info"))

        status_text = (
            "Выбран в качестве аналога"
            if is_analog else
            "Исключен по критерию"
        )

        ws.append([
            idx,
            data.get("address"),
            data.get("price"),
            data.get("area_m2"),
            price_per_m2,
            int(data.get("params", {}).get("Этаж")) if str(data.get("params", {}).get("Этаж", "")).isdigit() else None,
            data.get("params", {}).get("Площадь участка"),
            data.get("params", {}).get("Материал стен"),
            data.get("params", {}).get("Год постройки"),
            data.get("url"),
            data.get("description"),
            status_text
        ])

        row_idx = ws.max_row
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col)
            cell.border = border
            cell.alignment = align
            if col == 12 and is_analog:
                cell.font = bold

    # --- ШИРИНА СТОЛБЦОВ ---
    widths = [10, 20, 10, 10, 10, 10, 10, 10, 14, 30, 55, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # --- ВТОРАЯ ТАБЛИЦА ---
    analogs = [r["data"] for r in data_rows if r["is_analog"]]

    if analogs:
        start_row = ws.max_row + 3

        labels = [
            "Адрес",
            "Цена",
            "Площадь",
            "Цена за м²",
            "Этаж",
            "Площадь участка",
            "Ссылка"
        ]

        for i, label in enumerate(labels):
            cell = ws.cell(row=start_row + i, column=1, value=label)
            cell.font = bold
            cell.border = border
            cell.alignment = align

        for col_idx, analog in enumerate(analogs, start=2):
            values = [
                analog.get("address"),
                analog.get("price"),
                analog.get("area_m2"),
                extract_price_per_m2(analog.get("price_info")),
                int(data.get("params", {}).get("Этаж")) if str(analog.get("params", {}).get("Этаж", "")).isdigit() else None,
                analog.get("params", {}).get("Площадь участка"),
                analog.get("url"),
            ]

            for row_offset, value in enumerate(values):
                cell = ws.cell(
                    row=start_row + row_offset,
                    column=col_idx,
                    value=value
                )
                cell.border = border
                cell.alignment = align

    return wb
