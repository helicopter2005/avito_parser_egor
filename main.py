import sys
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMetaObject
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QLabel, QMessageBox, QHBoxLayout, QFileDialog,
    QTableWidget, QTableWidgetItem, QCheckBox
)
from openpyxl import Workbook
from avito_parser import AvitoParser
from selenium.common.exceptions import TimeoutException
from PyQt5.QtWidgets import QHeaderView

# =========================
# Worker (ФОН)
# =========================
class ParserWorker(QThread):
    log = pyqtSignal(str)
    captcha_detected = pyqtSignal()
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls
        self.parser = None
        self.success_count = 0

    def run(self):
        try:
            self.parser = AvitoParser(
                headless=False,
                slow_mode=True,
                on_captcha=self.on_captcha
            )

            wb = Workbook()
            ws = wb.active
            ws.title = "Avito"
            ws.append([
                "Ссылка", "Заголовок", "Цена",
                "Цена за м²", "История цены",
                "Адрес", "Площадь", "Описание"
            ])

            for i, url in enumerate(self.urls, 1):
                self.log.emit(f"[{i}/{len(self.urls)}] Парсинг: {url}")

                try:
                    data = self.parser.parse_ad(url)

                    if data.get("page_not_found"):
                        self.log.emit(f"❌ [{i}] Страница не существует")
                        continue

                except TimeoutException:
                    self.log.emit(f"❌ [{i}] Таймаут загрузки страницы")
                    continue

                price = data.get("price")
                area = data.get("area_m2")
                price_per_m2 = round(price / area, 2) if price and area else None

                history = "; ".join(
                    f"{h['date']} — {h['price']}₽"
                    for h in data.get("price_history", [])
                )

                ws.append([
                    data.get("url"),
                    data.get("title"),
                    price,
                    price_per_m2,
                    history,
                    data.get("address"),
                    area,
                    data.get("description"),
                ])

                self.success_count += 1

            self.parser.close()

            if self.success_count == 0:
                self.finished.emit(None)
            else:
                self.finished.emit(wb)

        except Exception as e:
            self.error.emit(str(e))

    def on_captcha(self):
        self.captcha_detected.emit()

    def continue_after_captcha(self):
        if self.parser:
            self.parser.continue_after_captcha()


# =========================
# GUI
# =========================
class AvitoApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Avito Parser — Аналоги")
        self.resize(900, 600)

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([
            "Ссылка",
            "Выбран как аналог"
        ])

        header = self.table.horizontalHeader()

        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Ссылка — растягивается
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Аналог — по тексту

        header.setStretchLastSection(False)

        self.add_btn = QPushButton("➕ Добавить ссылку")
        self.start_btn = QPushButton("▶ Запустить парсинг")
        self.continue_btn = QPushButton("⏯ Продолжить парсинг")
        self.continue_btn.setEnabled(False)

        self.log = QTableWidget()
        self.log.setColumnCount(1)
        self.log.setHorizontalHeaderLabels(["Лог"])
        self.log.horizontalHeader().setStretchLastSection(True)
        self.log.setRowCount(0)

        btns = QHBoxLayout()
        btns.addWidget(self.add_btn)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.continue_btn)

        layout.addWidget(QLabel("Ссылки на объявления Авито:"))
        layout.addWidget(self.table)
        layout.addLayout(btns)
        layout.addWidget(QLabel("Лог:"))
        layout.addWidget(self.log)

        self.add_btn.clicked.connect(self.add_row)
        self.start_btn.clicked.connect(self.start_parsing)
        self.continue_btn.clicked.connect(self.continue_parsing)

        self.worker = None

        for _ in range(5):
            self.add_row()

    # ---------- UI helpers ----------
    def add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(""))

        checkbox = QCheckBox()

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(checkbox)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table.setCellWidget(row, 1, container)

    def log_msg(self, text):
        row = self.log.rowCount()
        self.log.insertRow(row)
        self.log.setItem(row, 0, QTableWidgetItem(text))
        self.log.scrollToBottom()

    # ---------- Parsing ----------
    def start_parsing(self):
        urls = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip():
                urls.append(item.text().strip())

        if not urls:
            QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы одну ссылку")
            return

        self.start_btn.setEnabled(False)
        self.log.setRowCount(0)

        self.worker = ParserWorker(urls)
        self.worker.log.connect(self.log_msg)
        self.worker.captcha_detected.connect(self.on_captcha)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_captcha(self):
        self.log_msg("⚠ Обнаружена капча")
        self.continue_btn.setEnabled(True)

        QMessageBox.warning(
            self,
            "Капча",
            "Решите капчу в браузере,\n"
            "затем нажмите «Продолжить парсинг»"
        )

    def continue_parsing(self):
        if self.worker:
            QMetaObject.invokeMethod(
                self.worker,
                "continue_after_captcha",
                Qt.QueuedConnection
            )
            self.continue_btn.setEnabled(False)
            self.log_msg("▶ Парсинг продолжен")

    def on_finished(self, workbook):
        self.start_btn.setEnabled(True)

        if workbook is None:
            QMessageBox.information(self, "Готово", "Нет успешно обработанных объявлений")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить результат",
            "avito_results.xlsx",
            "Excel Files (*.xlsx)"
        )

        if not path:
            self.log_msg("❌ Сохранение отменено")
            return

        try:
            workbook.save(path)
            QMessageBox.information(self, "Готово", "Файл успешно сохранён")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def on_error(self, msg):
        self.start_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка", msg)


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AvitoApp()
    window.show()
    sys.exit(app.exec_())
