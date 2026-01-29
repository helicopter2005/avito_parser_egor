import sys
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMetaObject, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QLabel, QMessageBox, QHBoxLayout, QFileDialog,
    QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView
)

from selenium.common.exceptions import TimeoutException

from avito_parser import AvitoParser
from cian_parser import CianParser
from excel_builder import build_excel
from word_builder import build_word_with_screenshots



# =========================
# Worker (ФОН)
# =========================
class ParserWorker(QThread):
    log = pyqtSignal(str)
    captcha_detected = pyqtSignal()
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls
        self.parserAvito = None
        self.parserCian = None

    def run(self):
        try:
            self.parserAvito = AvitoParser(
                headless=False,
                slow_mode=True,
                on_captcha=self.on_captcha
            )

            self.parserCian = CianParser(
                headless=False,
                slow_mode=True,
                on_captcha=self.on_captcha
            )

            parsed_data = []

            avito_urls = []
            cian_urls = []

            for i, url in enumerate(self.urls, 1):
                url = url.split("?")[0]

                if "avito" in url:
                    try:
                        data = self.parserAvito.parse_ad(url)

                        if data.get("page_not_found"):
                            self.log.emit(f"❌ [{i}] Страница не существует")
                            continue
                    except TimeoutException:
                        self.log.emit(f"❌ [{i}] Таймаут загрузки страницы")
                        continue
                    parsed_data.append(data)

                elif "cian" in url:
                    try:
                        data = self.parserCian.parse_ad(url)

                        if data.get("page_not_found"):
                            self.log.emit(f"❌ [{i}] Страница не существует")
                            continue
                    except TimeoutException:
                        self.log.emit(f"❌ [{i}] Таймаут загрузки страницы")
                        continue
                    parsed_data.append(data)

            self.parserAvito.close()
            self.parserCian.close()

            result = {
                "rows": parsed_data
            }

            self.finished.emit(result)

        except Exception as e:
            self.error.emit(str(e))

    def on_captcha(self):
        self.captcha_detected.emit()

    @pyqtSlot()
    def continue_after_captcha(self):
        if self.parserAvito:
            self.parserAvito.continue_after_captcha()
        if self.parserCian:
            self.parserCian.continue_after_captcha()


# =========================
# GUI
# =========================
class AvitoApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Парсер объявлений Авито (оценка)")
        self.resize(900, 600)

        self.parsed_rows = []
        self.excel_workbook = None

        layout = QVBoxLayout(self)

        # ---------- Таблица ссылок ----------
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([
            "Ссылка",
            "Выбран как аналог"
        ])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)

        # ---------- Кнопки ----------
        self.add_btn = QPushButton("➕ Добавить ссылку")
        self.start_btn = QPushButton("▶ Запустить парсинг")
        self.continue_btn = QPushButton("⏯ Продолжить парсинг")
        self.export_excel_btn = QPushButton("Экспорт Excel")
        self.export_word_btn = QPushButton("Экспорт Word")

        self.continue_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.export_word_btn.setEnabled(False)

        # ---------- Лог ----------
        self.log = QTableWidget(0, 1)
        self.log.setHorizontalHeaderLabels(["Лог"])
        self.log.horizontalHeader().setStretchLastSection(True)

        btns = QHBoxLayout()
        btns.addWidget(self.add_btn)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.continue_btn)
        btns.addWidget(self.export_excel_btn)
        btns.addWidget(self.export_word_btn)

        layout.addWidget(QLabel("Ссылки на объявления с Авито:"))
        layout.addWidget(self.table)
        layout.addLayout(btns)
        layout.addWidget(QLabel("Вывод:"))
        layout.addWidget(self.log)

        self.add_btn.clicked.connect(self.add_row)
        self.start_btn.clicked.connect(self.start_parsing)
        self.continue_btn.clicked.connect(self.continue_parsing)
        self.export_excel_btn.clicked.connect(self.export_excel)
        self.export_word_btn.clicked.connect(self.export_word)

        self.worker = None

        # 5 строк при старте
        for _ in range(5):
            self.add_row()

    # ---------- UI helpers ----------
    def add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(""))

        checkbox = QCheckBox()
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.addWidget(checkbox)
        lay.setAlignment(Qt.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)

        self.table.setCellWidget(row, 1, container)

    def log_msg(self, text):
        row = self.log.rowCount()
        self.log.insertRow(row)
        self.log.setItem(row, 0, QTableWidgetItem(text))
        self.log.scrollToBottom()

    def get_current_rows_with_analogs(self):
        rows = []

        for i, data in enumerate(self.parsed_rows):
            widget = self.table.cellWidget(i, 1)
            checkbox = widget.layout().itemAt(0).widget()
            is_analog = checkbox.isChecked()

            rows.append({
                "data": data,
                "is_analog": is_analog
            })

        return rows

    # ---------- Parsing ----------
    def start_parsing(self):
        urls = []

        self.parsed_rows = []
        self.excel_workbook = None
        self.export_excel_btn.setEnabled(False)
        self.export_word_btn.setEnabled(False)

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            widget = self.table.cellWidget(row, 1)
            checkbox = widget.layout().itemAt(0).widget()

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
        self.log_msg("⚠ Обнаружена капча или требуется авторизация")
        self.continue_btn.setEnabled(True)

        QMessageBox.warning(
            self,
            "Требуется действие",
            "Решите капчу или авторизуйтесь в браузере,\n"
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

    def on_finished(self, result):
        self.start_btn.setEnabled(True)

        if result is None:
            QMessageBox.information(self, "Готово", "Нет успешно обработанных объявлений")
            return

        self.parsed_rows = result["rows"]

        self.export_excel_btn.setEnabled(True)
        self.export_word_btn.setEnabled(True)

        QMessageBox.information(self, "Готово", "Парсинг завершён. Данные готовы к экспорту.")

    def on_error(self, msg):
        self.start_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка", msg)

    def export_excel(self):
        if not self.parsed_rows:
            return

        rows = self.get_current_rows_with_analogs()

        wb = build_excel(self, rows)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить Excel",
            "avito_results.xlsx",
            "Excel Files (*.xlsx)"
        )

        if not path:
            return

        try:
            wb.save(path)
            QMessageBox.information(self, "Готово", "Excel файл сохранён")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def export_word(self):
        if not self.parsed_rows:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить Word",
            "Аналоги.docx",
            "Word Files (*.docx)"
        )

        if not path:
            return

        rows = self.get_current_rows_with_analogs()

        try:
            build_word_with_screenshots(
                rows,
                path
            )
            QMessageBox.information(self, "Готово", "Word файл сохранён")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AvitoApp()
    window.show()
    sys.exit(app.exec_())
