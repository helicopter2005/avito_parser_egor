import sys
import os
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMetaObject, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QLabel, QMessageBox, QHBoxLayout, QFileDialog,
    QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView
)

from selenium.common.exceptions import TimeoutException

import hashlib
import uuid
import base64

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

    def __init__(self, urls, parserAvito=None, parserCian=None):
        super().__init__()
        self.urls = urls
        self.parserAvito = parserAvito
        self.parserCian = parserCian

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
        self.setWindowTitle("Парсер объявлений (оценка)")
        self.resize(900, 600)

        self.parsed_rows = []
        self.excel_workbook = None

        self.parserAvito = None
        self.parserCian = None

        self.is_trial = True  # False для полной версии
        self.trial_limit = 10
        self.parsed_count = self._load_parsed_count()

        layout = QVBoxLayout(self)

        if self.is_trial:
            remaining = max(0, self.trial_limit - self.parsed_count)
            self.trial_label = QLabel(f"🔓Пробная версия: осталось {remaining} из {self.trial_limit} объявлений")
            layout.addWidget(self.trial_label)

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

        # ПРОВЕРКА ТРИАЛА
        if self.is_trial:
            remaining = self.trial_limit - self.parsed_count

            if remaining <= 0:
                QMessageBox.warning(
                    self,
                    "Триал исчерпан",
                    f"Вы исчерпали лимит пробной версии ({self.trial_limit} объявлений).\n"
                    "Для продолжения работы приобретите полную версию."
                )
                return

            if len(urls) > remaining:
                reply = QMessageBox.question(
                    self,
                    "Превышен лимит",
                    f"У вас осталось {remaining} объявлений.\n"
                    f"Распарсить только первые {remaining}?",
                    QMessageBox.Yes | QMessageBox.No
                )

                if reply == QMessageBox.Yes:
                    urls = urls[:remaining]
                else:
                    return

        self.start_btn.setEnabled(False)
        self.log.setRowCount(0)

        self.worker = ParserWorker(urls, self.parserAvito, self.parserCian)
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

        if self.worker:
            self.parserAvito = self.worker.parserAvito
            self.parserCian = self.worker.parserCian

        if result is None:
            QMessageBox.information(self, "Готово", "Нет успешно обработанных объявлений")
            return

        self.parsed_rows = result["rows"]

        if self.is_trial and len(self.parsed_rows) > 0:
            self.parsed_count += len(self.parsed_rows)
            self._save_parsed_count()
            self._update_trial_label()

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

    def _get_cache_dir(self):
        """Определение папки для хранения файла счетчика"""
        # Для PyInstaller - папка _internal рядом с exe
        if getattr(sys, 'frozen', False):
            # Путь к exe файлу
            app_dir = os.path.dirname(sys.executable)
            cache_dir = os.path.join(app_dir, '_internal')
        else:
            # Для разработки - текущая директория
            cache_dir = os.path.dirname(os.path.abspath(__file__))

        # Создаем папку, если её нет
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _get_cache_file_path(self):
        """Получение полного пути к файлу кэша"""
        cache_dir = self._get_cache_dir()
        return os.path.join(cache_dir, "app_cache_tmp.dat")

    def _get_machine_id(self):
        """Получение уникального ID машины"""
        try:
            machine_id = str(uuid.getnode())
            return hashlib.md5(machine_id.encode()).hexdigest()[:16]
        except:
            return "default00machine"

    def _encrypt_data(self, data):
        """Простое шифрование данных"""
        machine_id = self._get_machine_id()
        # XOR с machine_id
        encrypted = ''.join(chr(ord(c) ^ ord(machine_id[i % len(machine_id)])) for i, c in enumerate(str(data)))
        # Base64 для безопасного хранения
        return base64.b64encode(encrypted.encode()).decode()

    def _decrypt_data(self, encrypted_data):
        """Дешифрование данных"""
        try:
            machine_id = self._get_machine_id()
            # Декодируем из Base64
            decoded = base64.b64decode(encrypted_data.encode()).decode()
            # XOR обратно
            decrypted = ''.join(chr(ord(c) ^ ord(machine_id[i % len(machine_id)])) for i, c in enumerate(decoded))
            return int(decrypted)
        except:
            return 0

    def _load_parsed_count(self):
        """Загрузка счетчика из файла"""
        try:
            cache_file = self._get_cache_file_path()
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    encrypted = f.read().strip()
                    return self._decrypt_data(encrypted)
        except Exception as e:
            print(f"Ошибка загрузки счетчика: {e}")
        return 0

    def _save_parsed_count(self):
        """Сохранение счетчика в файл"""
        try:
            cache_file = self._get_cache_file_path()
            encrypted = self._encrypt_data(self.parsed_count)
            with open(cache_file, 'w') as f:
                f.write(encrypted)
        except Exception as e:
            print(f"Ошибка сохранения: {e}")

    def _update_trial_label(self):
        """Обновление лейбла с информацией о триале"""
        if not self.is_trial:
            return

        remaining = max(0, self.trial_limit - self.parsed_count)
        self.trial_label.setText(f"🔓 Пробная версия: осталось {remaining} из {self.trial_limit} объявлений")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AvitoApp()
    window.show()
    sys.exit(app.exec_())
