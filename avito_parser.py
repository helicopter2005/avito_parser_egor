"""
Avito Real Estate Parser
Парсер объявлений недвижимости с Avito используя Selenium

Установка зависимостей:
pip install selenium webdriver-manager requests
"""

import os
import sys
import re
import json
import time
import hashlib
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(relative_path)

class AvitoParser:
    """Парсер объявлений недвижимости Avito"""

    def __init__(self, headless=False, download_images=True, images_dir="Скриншоты", slow_mode=False, on_captcha=None):
        self.download_images = download_images
        self.images_dir = Path(images_dir)
        self.driver = None
        self.headless = headless
        self.slow_mode = slow_mode
        self.slow_delay = 0.4
        self.on_captcha = on_captcha
        self._wait_for_user = False
        self.browser_type = None

        if download_images:
            self.images_dir.mkdir(parents=True, exist_ok=True)

    def _setup_driver(self):
        """Настройка драйвера с fallback: Yandex → Chrome"""
        options = Options()

        if self.headless:
            options.add_argument("--headless=new")

        # Общие параметры для обоих браузеров
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--lang=ru-RU")
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-extensions')
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.page_load_strategy = "eager"

        # Попытка 1: Yandex Browser с yandexdriver.exe
        yandex_driver_path = resource_path("yandexdriver.exe")  # или полный путь: "C:/drivers/yandexdriver.exe"

        if os.path.exists(yandex_driver_path):
            try:
                print("🔍 Найден yandexdriver.exe, запускаю Yandex Browser...")
                service = Service(yandex_driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)
                self.browser_type = "yandex"
                print("✓ Yandex Browser успешно запущен")
            except Exception as e:
                print(f"✗ Ошибка запуска Yandex Browser: {e}")
                print("↻ Переключаюсь на Chrome...")
                self.driver = None
        else:
            print(f"ℹ yandexdriver.exe не найден по пути: {yandex_driver_path}")
            print("↻ Переключаюсь на Chrome...")

        # Попытка 2: Chrome (если Yandex не запустился)
        if self.driver is None:
            try:
                print("🔍 Запускаю Chrome...")
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                self.browser_type = "chrome"
                print("✓ Chrome успешно запущен")
            except Exception as e:
                raise Exception(f"Не удалось запустить ни Yandex, ни Chrome: {e}")

        # Применяем антидетект скрипты
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
            """
        })

        return self.driver

    def _wait_for_page_load(self, timeout=60):
        """Циклическая проверка tooltip каждые 3 секунды"""
        max_attempts = 20

        for attempt in range(1, max_attempts + 1):
            print(f"  Попытка {attempt}/{max_attempts}: ждём 3 сек...")
            time.sleep(1)



            # Проверяем tooltip
            try:
                from selenium.webdriver.common.action_chains import ActionChains

                elements = self.driver.find_elements(By.XPATH,
                                                     "//*[contains(text(), 'История цены')]")

                for el in elements:
                    try:
                        if el.is_displayed() and el.size['width'] > 0:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                            time.sleep(0.3)

                            actions = ActionChains(self.driver)
                            actions.move_to_element(el).perform()
                            time.sleep(1)

                            # Ищем tooltip
                            tooltips = self.driver.find_elements(By.CSS_SELECTOR,
                                                                 "[class*='tooltip'], [class*='Tooltip'], [class*='popup'], [role='tooltip']")

                            for t in tooltips:
                                try:
                                    if t.is_displayed() and '₽' in t.text:
                                        print("  ✓ Tooltip найден, начинаем парсинг")
                                        actions.move_by_offset(300, 300).perform()
                                        return  # Успех!
                                except:
                                    continue

                            actions.move_by_offset(300, 300).perform()
                            print(f"  ⚠ Tooltip не появился (попытка {attempt})")
                            break
                    except:
                        continue
                else:
                    print(f"  ⚠ Элемент 'История цены' не найден (попытка {attempt})")

            except Exception as e:
                print(f"  ⚠ Ошибка попытки {attempt}: {e}")

        try:
            # Ждём только interactive, не complete
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") in ["interactive", "complete"]
            )
        except TimeoutException:
            print("  Таймаут базовой загрузки")

    def _get_price_history_and_screenshot(self, address_ad):
        """Получение истории цен + скриншот с открытым tooltip"""
        price_history = []
        screenshot_path = None

        try:
            from selenium.webdriver.common.action_chains import ActionChains

            hover_element = None
            elements = self.driver.find_elements(By.XPATH,
                                                 "//*[contains(text(), 'История цены')]")
            for el in elements:
                try:
                    if el.is_displayed() and el.size['width'] > 0:
                        hover_element = el
                        break
                except:
                    continue

            if hover_element:
                self._slow_pause("Навожу на 'История цены'...")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", hover_element)
                time.sleep(0.3)

                actions = ActionChains(self.driver)
                actions.move_to_element(hover_element).perform()
                time.sleep(1)

                # Делаем скриншот с открытым tooltip
                ad_folder = self.images_dir / str(address_ad)
                ad_folder.mkdir(parents=True, exist_ok=True)
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.3)
                top_path = ad_folder / "история цены.png"
                self.driver.save_screenshot(str(top_path))
                screenshot_path = str(top_path)
                print(f"  ✓ Скриншот (цена+история): {top_path.name}")

                # Парсим tooltip
                tooltip_selectors = [
                    "[class*='tooltip']", "[class*='Tooltip']", "[class*='popup']",
                    "[class*='Popup']", "[role='tooltip']", "[class*='popper']"
                ]

                tooltip = None
                for selector in tooltip_selectors:
                    try:
                        tooltips = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for t in tooltips:
                            if t.is_displayed() and '₽' in t.text and len(t.text) > 10:
                                tooltip = t
                                break
                    except:
                        continue
                    if tooltip:
                        break

                if tooltip:
                    text = tooltip.text.replace('\xa0', ' ')
                    text = re.sub(r'\s+', ' ', text).strip()
                    tokens = text.split(' ')

                    i = 0
                    while i < len(tokens):
                        if (i + 2 < len(tokens) and re.match(r'\d{1,2}', tokens[i])
                                and re.match(r'[А-Яа-я]+', tokens[i + 1])
                                and re.match(r'\d{4}', tokens[i + 2])):
                            date = f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}"
                            i += 3

                            num_parts = []
                            while i < len(tokens) and re.match(r'\d+', tokens[i]):
                                num_parts.append(tokens[i])
                                i += 1

                            if i < len(tokens) and tokens[i] == '₽':
                                price = int(''.join(num_parts))
                                price_history.append({"date": date, "price": price})
                                i += 1

                            while i < len(tokens):
                                if tokens[i].isdigit() and i + 1 < len(tokens) and tokens[i + 1] == '₽':
                                    i += 2
                                    break
                                if tokens[i] in ('Публикация', 'Следить'):
                                    break
                                i += 1
                            continue
                        i += 1

                    print(f"  ✓ История цен: {len(price_history)} записей")

                # Убираем курсор
                actions.move_by_offset(300, 300).perform()
                time.sleep(0.3)
            else:
                print("  ℹ Элемент 'История цены' не найден")
        except Exception as e:
            print(f"  ✗ Ошибка истории цен: {e}")

        return price_history, screenshot_path

    def _take_bottom_screenshot(self, address_ad):
        """Скриншот нижней части без tooltip"""
        try:
            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            bottom_path = ad_folder / "дата публикации.png"
            self.driver.save_screenshot(str(bottom_path))
            print(f"  ✓ Скриншот (низ): {bottom_path.name}")
            return str(bottom_path)
        except Exception as e:
            print(f"  ✗ Ошибка скриншота: {e}")
            return None

    def continue_after_captcha(self):
        self._wait_for_user = False

    def _slow_pause(self, message=""):
        if self.slow_mode:
            if message:
                print(f"  [SLOW MODE] {message}")
            time.sleep(self.slow_delay)

    def _extract_text(self, selectors, default=""):
        for selector in selectors:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, selector)
                text = el.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                continue
        return default

    def _parse_price(self, price_text):
        if not price_text:
            return None, None

        numbers = re.findall(r'[\d\s]+', price_text)
        if numbers:
            price_str = numbers[0].replace(' ', '').replace('\xa0', '')
            try:
                price = int(price_str)
            except ValueError:
                price = None
        else:
            price = None

        price_type = "месяц"
        if "м²" in price_text or "м2" in price_text:
            price_type = "м²/месяц"
        elif "год" in price_text:
            price_type = "год"

        return price, price_type

    def _convert_to_max_quality(self, url):
        if not url:
            return None

        # Убираем query-параметры размера
        converted = re.sub(r'[?&]s=\d+x\d+', '', url)
        converted = re.sub(r'[?&]w=\d+', '', converted)
        converted = re.sub(r'[?&]h=\d+', '', converted)

        if converted.endswith('?'):
            converted = converted[:-1]

        return converted

    def _extract_params(self):
        params = {}
        try:
            param_items = self.driver.find_elements(By.CSS_SELECTOR,
                "[data-marker='item-view/item-params'] li, [class*='params-paramsList'] li")

            for item in param_items:
                text = item.text.strip()
                if ':' in text:
                    key, value = text.split(':', 1)
                    params[key.strip()] = value.strip()
                elif '\n' in text:
                    parts = text.split('\n')
                    if len(parts) >= 2:
                        params[parts[0].strip()] = parts[1].strip()
        except:
            pass
        return params

    def parse_ad(self, url):
        if not self.driver:
            self._setup_driver()

        print(f"\nПарсинг: {url}")

        ad_id_match = re.search(r'_(\d+)(?:\?|$)', url)
        ad_id = ad_id_match.group(1) if ad_id_match else hashlib.md5(url.encode()).hexdigest()[:10]

        self.driver.get(url)
        time.sleep(2)

        # Проверяем капчу/блокировку по реальным признакам
        page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()

        if (
                "такой страницы не существует" in page_text
                or "страница не найдена" in page_text
                or "объявление не найдено" in page_text
        ):
            return {
                "url": url,
                "page_not_found": True
            }

        is_blocked = any(phrase in page_text for phrase in [
            "подтвердите, что вы не робот",
            "доступ ограничен",
            "заблокирован",
            "access denied",
            "проверка безопасности"
        ])

        # Также проверяем отсутствие основного контента
        try:
            self.driver.find_element(By.CSS_SELECTOR, "[data-marker='item-view/title-info'], h1")
            has_content = True
        except:
            has_content = False

        if is_blocked or not has_content:
            self._wait_for_user = True

            if self.on_captcha:
                self.on_captcha()

            while self._wait_for_user:
                time.sleep(0.3)

            self._wait_for_page_load()
        self._wait_for_page_load()
        data = {
            "id": ad_id,
            "url": url,
            "parsed_at": datetime.now().isoformat(),
        }

        data["title"] = self._extract_text([
            "[data-marker='item-view/title-info'] h1",
            "h1[itemprop='name']",
            ".title-info-title span",
            "h1"
        ])

        price_text = self._extract_text([
            "[data-marker='item-view/item-price']",
            "[class*='style-price-value']",
            "[class*='price-value']",
            "[class*='item-price']",
            "[itemprop='price']",
            ".js-item-price"
        ])

        # Если основная цена не найдена, ищем по тексту с ₽
        if not price_text:
            try:
                elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), '₽')]")
                for el in elements:
                    text = el.text.strip()
                    # Ищем формат "XXX XXX ₽ в месяц"
                    if '₽' in text and ('месяц' in text.lower() or 'год' in text.lower()):
                        price_text = text
                        break
            except:
                pass

        data["price_text"] = price_text
        data["price"], data["price_type"] = self._parse_price(price_text)

        # Дополнительная инфо о цене (за м², залог)
        price_info = self._extract_text([
            "[class*='price-info']",
            "[class*='price-sub']",
            "[class*='style-price-sub']"
        ])
        if not price_info:
            try:
                # Ищем текст под ценой
                price_el = self.driver.find_element(By.XPATH, "//*[contains(text(), '₽ в месяц')]")
                parent = price_el.find_element(By.XPATH, "./..")
                siblings = parent.find_elements(By.XPATH, "./following-sibling::*")
                for sib in siblings[:3]:
                    text = sib.text.strip()
                    if 'м²' in text or 'залог' in text.lower():
                        price_info = text
                        break
            except:
                pass
        data["price_info"] = price_info

        # История цен + скриншот с tooltip
        print("  Получение истории цен и скриншота...")
        data["price_history"], top_screenshot = self._get_price_history_and_screenshot(data['title'])

        data["address"] = self._extract_text([
            "[data-marker='delivery/location']",
            "[itemprop='address']",
            ".style-item-address__string",
            "[class*='item-address'] span",
            "[class*='geo-address']"
        ])

        data["description"] = self._extract_text([
            "[data-marker='item-view/item-description']",
            "[itemprop='description']",
            ".item-description-text",
        ])

        data["params"] = self._extract_params()

        area_match = re.search(r'(\d+[.,]?\d*)\s*м[²2]', data.get("title", "") + str(data.get("params", {})))
        if area_match:
            data["area_m2"] = float(area_match.group(1).replace(',', '.'))

        data["seller_name"] = self._extract_text([
            "[data-marker='seller-info/name']",
            ".seller-info-name",
            "[class*='seller-info'] a"
        ])

        data["published_date"] = self._extract_text([
            "[data-marker='item-view/item-date']",
            ".style-item-metadata-date",
            "[class*='date-info']"
        ])

        # Если в объявлении указана только цена за м2 в месяц
        if "в месяц за м²" in data["price_text"]:
            if area_match:
                data["price"] = round(data["price"] * data["area_m2"], 1)
            else:
                data["price"] = "Введите стоимость аренды вручную"

        # Нижний скриншот
        bottom_screenshot = self._take_bottom_screenshot(data['title'])
        data["screenshots"] = {"top": top_screenshot, "bottom": bottom_screenshot}
        print(f"  ✓ Заголовок: {data.get('title', 'Не найден')[:50]}...")
        print(f"  ✓ Цена: {data.get('price_text', 'Не найдена')}")
        print(f"  ✓ Изображений: {data.get('images_count', 0)}")

        return data

    def parse_multiple(self, urls):
        results = []
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] ", end="")
            try:
                data = self.parse_ad(url)
                results.append(data)
                if i < len(urls):
                    delay = 3 + (i % 3)
                    print(f"  Пауза {delay} сек...")
                    time.sleep(delay)
            except Exception as e:
                print(f"  ✗ Ошибка: {e}")
                results.append({"url": url, "error": str(e)})
        return results

    def save_results(self, results, filename="avito_results.json"):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nРезультаты сохранены в {filename}")

    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None