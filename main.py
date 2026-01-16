import sys
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QTextEdit, QLabel, QMessageBox, QHBoxLayout, QFileDialog
)
from openpyxl import Workbook
from avito_parser import AvitoParser
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtCore import QMetaObject, Qt
from selenium.common.exceptions import TimeoutException, WebDriverException



# =========================
# Worker (ФОН)
# =========================
class ParserWorker(QThread):
    log = pyqtSignal(str)
    captcha_detected = pyqtSignal()
    finished = pyqtSignal(object)  # Workbook
    error = pyqtSignal(str)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls
        self.success_count = 0

    @pyqtSlot()
    def continue_after_captcha(self):
        if self.parser:
            self.parser.continue_after_captcha()

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
                        self.log.emit(
                            f"❌ [{i}] Страница не существует: {url}"
                        )
                        continue

                except TimeoutException:
                    self.log.emit(
                        f"❌ [{i}] Таймаут загрузки страницы: {url}"
                    )
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

    def continue_parsing(self):
        if self.worker:
            QMetaObject.invokeMethod(
                self.worker,
                "continue_after_captcha",
                Qt.QueuedConnection
            )
            self.continue_btn.setEnabled(False)
            self.log_msg("▶ Продолжение парсинга")


# =========================
# GUI
# =========================
class AvitoApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Avito Parser")
        self.resize(800, 600)


        layout = QVBoxLayout(self)

        self.urls_input = QTextEdit()
        self.urls_input.setPlaceholderText("Каждая ссылка с новой строки")

        self.start_btn = QPushButton("▶ Запустить парсинг")
        self.continue_btn = QPushButton("⏯ Продолжить парсинг")
        self.continue_btn.setEnabled(False)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        btns = QHBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.continue_btn)

        layout.addWidget(QLabel("Ссылки:"))
        layout.addWidget(self.urls_input)
        layout.addLayout(btns)
        layout.addWidget(QLabel("Лог:"))
        layout.addWidget(self.log)

        self.start_btn.clicked.connect(self.start_parsing)
        self.continue_btn.clicked.connect(self.continue_parsing)

        self.worker = None

    def log_msg(self, text):
        self.log.append(text)

    def continue_after_captcha(self):
        if self.parser:
            self.parser.continue_after_captcha()

    def continue_parsing(self):
        if self.worker:
            self.worker.continue_after_captcha()
            self.continue_btn.setEnabled(False)
            self.log_msg("▶ Парсинг продолжен")

    def start_parsing(self):
        urls = [u.strip() for u in self.urls_input.toPlainText().splitlines() if u.strip()]
        if not urls:
            QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы одну ссылку")
            return

        self.start_btn.setEnabled(False)
        self.log.clear()

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

    def on_finished(self, workbook):
        self.start_btn.setEnabled(True)

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
        except PermissionError:
            QMessageBox.warning(self, "Ошибка", "Файл открыт в Excel")
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
