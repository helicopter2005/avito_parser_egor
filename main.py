import sys
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMetaObject, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QLabel, QMessageBox, QHBoxLayout, QFileDialog,
    QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView, QMenuBar, QAction, QDialog, QDialogButtonBox
)
from PyQt5.QtGui import QIcon

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
    auth_required = pyqtSignal()
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, urls, parserAvito=None, parserCian=None, download_photos=False):
        super().__init__()
        self.urls = urls
        self.parserAvito = parserAvito
        self.parserCian = parserCian
        self.download_photos = download_photos

    def run(self):
        try:
            # Проверяем и переиспользуем или создаем новый парсер Avito
            if self.parserAvito is None or self.parserAvito.driver is None:
                self.parserAvito = AvitoParser(
                    headless=False,
                    slow_mode=True,
                    on_captcha=self.on_captcha
                )
            else:
                # Проверяем, что браузер еще жив
                try:
                    self.parserAvito.driver.current_url
                except:
                    self.log.emit("ℹ Браузер Avito был закрыт, открываем новый...")
                    self.parserAvito = AvitoParser(
                        headless=False,
                        slow_mode=True,
                        on_captcha=self.on_captcha
                    )

            # Проверяем и переиспользуем или создаем новый парсер Cian
            if self.parserCian is None or self.parserCian.driver is None:
                self.parserCian = CianParser(
                    headless=False,
                    slow_mode=True,
                    on_captcha=self.on_captcha,
                    on_auth=self.on_auth
                )
            else:
                # Проверяем, что браузер еще жив
                try:
                    self.parserCian.driver.current_url
                except:
                    self.log.emit("ℹ Браузер Cian был закрыт, открываем новый...")
                    self.parserCian = CianParser(
                        headless=False,
                        slow_mode=True,
                        on_captcha=self.on_captcha,
                        on_auth=self.on_auth
                    )

            if self.parserAvito:
                self.parserAvito.download_photos = self.download_photos

            if self.parserCian:
                self.parserCian.download_photos = self.download_photos

            parsed_data = []

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

            result = {
                "rows": parsed_data
            }

            self.finished.emit(result)

        except Exception as e:
            self.error.emit(str(e))

    def on_captcha(self):
        self.captcha_detected.emit()

    def on_auth(self):
        self.auth_required.emit()

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
        self.initUI()
        self.resize(900, 600)

        self.parsed_rows = []
        self.excel_workbook = None

        self.parserAvito = None
        self.parserCian = None

        self.save_photos = False

        menubar = QMenuBar(self)

        # Меню Фото
        photo_menu = menubar.addMenu("Фото")
        self.save_photos_action = QAction("Сохранять фото", self, checkable=True)
        self.save_photos_action.toggled.connect(self.on_save_photos_toggled)
        photo_menu.addAction(self.save_photos_action)

        # Меню Контакты
        contacts_action = QAction("Контакты", self)
        contacts_action.triggered.connect(self.show_contacts)
        menubar.addAction(contacts_action)

        layout = QVBoxLayout(self)

        layout.setMenuBar(menubar)

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
        self.clear_btn = QPushButton("🗑 Очистить поля")

        self.continue_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.export_word_btn.setEnabled(False)

        # ---------- Лог ----------
        self.log = QTableWidget(0, 1)
        self.log.setHorizontalHeaderLabels([""])
        self.log.horizontalHeader().setStretchLastSection(True)

        btns = QHBoxLayout()
        btns.addWidget(self.add_btn)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.continue_btn)
        btns.addWidget(self.export_excel_btn)
        btns.addWidget(self.export_word_btn)
        btns.addWidget(self.clear_btn)

        layout.addWidget(QLabel("Ссылки на объявления:"))
        layout.addWidget(self.table)
        layout.addLayout(btns)
        layout.addWidget(QLabel("Журнал:"))
        layout.addWidget(self.log)

        self.add_btn.clicked.connect(self.add_row)
        self.start_btn.clicked.connect(self.start_parsing)
        self.continue_btn.clicked.connect(self.continue_parsing)
        self.export_excel_btn.clicked.connect(self.export_excel)
        self.export_word_btn.clicked.connect(self.export_word)
        self.clear_btn.clicked.connect(self.clear_fields)

        self.worker = None

        # 5 строк при старте
        for _ in range(5):
            self.add_row()

    # ---------- UI helpers ----------

    def initUI(self):
        self.setWindowTitle('Пример смены иконки')
        self.setGeometry(100, 100, 300, 200)

        self.setWindowIcon(QIcon('icon.ico'))

        self.show()

    def on_save_photos_toggled(self, checked):
        self.save_photos = checked
        self.log_msg(f"{'✓ Фото будут сохраняться' if checked else 'ℹ Сохранение фото отключено'}")

    def show_contacts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Контакты")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("gekk1337@gmail.com"))
        btn = QDialogButtonBox(QDialogButtonBox.Ok)
        btn.accepted.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec_()

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

    def clear_fields(self):
        """Очистка всех полей ввода и возврат к 5 строкам"""
        # Удаляем все строки
        self.table.setRowCount(0)

        # Добавляем обратно 5 пустых строк
        for _ in range(5):
            self.add_row()

        self.log_msg("✓ Поля очищены")

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

    def closeEvent(self, event):
        """Закрытие браузеров при выходе из приложения"""
        if self.parserAvito:
            self.parserAvito.close()
        if self.parserCian:
            self.parserCian.close()
        event.accept()

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

        self.worker = ParserWorker(urls, self.parserAvito, self.parserCian, self.save_photos)
        self.worker.log.connect(self.log_msg)
        self.worker.captcha_detected.connect(self.on_captcha)
        self.worker.auth_required.connect(self.on_auth)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_captcha(self):
        self.log_msg("⚠ Обнаружена капча")
        self.continue_btn.setEnabled(True)

        msg = QMessageBox(self)
        msg.setWindowTitle("Требуется действие")
        msg.setText("Решите капчу или авторизуйтесь в браузере,\n"
                    "затем нажмите «Продолжить парсинг»")
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowFlags(Qt.WindowType(msg.windowFlags() | Qt.WindowStaysOnTopHint))  # НОВАЯ СТРОКА
        msg.exec_()

    def on_auth(self):
        self.log_msg("⚠ Требуется авторизация")
        self.continue_btn.setEnabled(True)

        msg = QMessageBox(self)
        msg.setWindowTitle("Требуется авторизация")
        msg.setText("Пожалуйста, авторизуйтесь в браузере,\n"
                    "затем нажмите «Продолжить парсинг»")
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowFlags(Qt.WindowType(msg.windowFlags() | Qt.WindowStaysOnTopHint))  # НОВАЯ СТРОКА
        msg.exec_()

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

        # Сохраняем парсеры из worker'а для переиспользования
        if self.worker:
            self.parserAvito = self.worker.parserAvito
            self.parserCian = self.worker.parserCian

        if result is None:
            QMessageBox.information(self, "Готово", "Нет успешно обработанных объявлений")
            return

        self.parsed_rows = result["rows"]

        self.export_excel_btn.setEnabled(True)
        self.export_word_btn.setEnabled(True)

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Готово")
        msg_box.setText("Парсинг завершён. Данные готовы к экспорту.")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowFlags(Qt.WindowType(msg_box.windowFlags() | Qt.WindowStaysOnTopHint))
        msg_box.exec_()

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
