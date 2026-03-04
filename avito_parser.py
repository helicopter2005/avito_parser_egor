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
import asyncio
import aiohttp
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from PIL import Image


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(relative_path)

class AvitoParser:
    """Парсер объявлений недвижимости Avito"""

    def __init__(self, headless=False, download_screens=True, download_photos = False, images_dir="Скриншоты", slow_mode=False, on_captcha=None):
        self.download_screens = download_screens
        self.download_photos = download_photos
        self.images_dir = Path(images_dir)
        self.driver = None
        self.headless = headless
        self.slow_mode = slow_mode
        self.slow_delay = 0.4
        self.on_captcha = on_captcha
        self._wait_for_user = False
        self.browser_type = None

        if download_screens:
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
        yandex_driver_path = resource_path("yandexdriver.exe")

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
            print(f"  Попытка {attempt}/{max_attempts}: ждём 2 сек...")
            time.sleep(1)

            try:

                elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    'button[aria-label="История цены"]'
                )

                if not elements:
                    elements = self.driver.find_elements(By.XPATH,
                                                         "//*[contains(text(), 'История цены')]")
                if not elements:
                    raise Exception("История цены не найдена")
            except Exception as e:
                print(str(e))
                break

            # Проверяем tooltip
            try:
                from selenium.webdriver.common.action_chains import ActionChains

                try:
                    elements = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        'button[aria-label="История цены"]'
                    )

                    if not elements:
                        elements = self.driver.find_elements(By.XPATH,
                                                             "//*[contains(text(), 'История цены')]")
                except Exception as e:
                    print(str(e))

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
                                        return True # Успех!
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

        return False

    def _get_main_container(self):
        content_container = self.driver.find_element(
            By.CSS_SELECTOR,
            "[data-marker*='title']"
        )
        # затем поднимаемся к родителю нужного уровня
        content_container = self.driver.execute_script(
            "return arguments[0].parentElement.parentElement.parentElement.parentElement.parentElement;",
            content_container
        )

        return content_container

    def _get_price_history_and_screenshot(self, address_ad):
        """Получение истории цен + скриншот tooltip, обрезанный по контейнеру контента"""
        import time
        import re
        from PIL import Image
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains

        price_history = []
        screenshot_path = None

        hover_element = None
        elements = self.driver.find_elements(
            By.CSS_SELECTOR,
            'button[aria-label="История цены"]'
        )

        if not elements:
            elements = self.driver.find_elements(By.XPATH,
                                                 "//*[contains(text(), 'История цены')]")

        for el in elements:
            try:
                if el.is_displayed() and el.size["width"] > 0:
                    hover_element = el
                    break
            except Exception:
                continue

        try:
            self.driver.execute_script(
                """arguments[0].scrollIntoView({block: 'center'});
                window.scrollBy(0, 20);""",
                hover_element
            )
        except Exception as e:
            print(str(e))


        try:
            driver = self.driver
            content_container = self._get_main_container()

            try:
                ads_selectors = [
                    "div[class*='item-view-ads']",
                    "div[class*='ads']",
                    "div[data-marker*='ads']"
                ]

                for selector in ads_selectors:
                    ads = content_container.find_elements(By.CSS_SELECTOR, selector)
                    for ad in ads:
                        self.driver.execute_script("arguments[0].remove();", ad)

            except Exception:
                pass

            ActionChains(self.driver).move_to_element(hover_element).perform()

            time.sleep(1)

            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            full_path = ad_folder / "_tmp_full.png"
            driver.save_screenshot(str(full_path))

            rect = driver.execute_script("""
                var r = arguments[0].getBoundingClientRect();
                return {left:r.left, top:r.top, width:r.width, height:r.height};
            """, content_container)

            dpr = driver.execute_script("return window.devicePixelRatio || 1;")

            left = int(rect["left"] * dpr)
            top = int(rect["top"] * dpr)
            right = int((rect["left"] + rect["width"]) * dpr)
            bottom = int((rect["top"] + rect["height"]) * dpr)

            img = Image.open(full_path)
            img_w, img_h = img.size

            # 🔧 защита от чёрных прямоугольников
            left = max(0, left)
            top = max(0, top)
            right = min(img_w, right)
            bottom = min(img_h, bottom)

            final_path = ad_folder / "история цены.png"
            img.crop((left, top, right, bottom)).save(final_path)
            screenshot_path = str(final_path)

            full_path.unlink(missing_ok=True)

            print(f"  ✓ Скриншот (история цены): {final_path.name}")

            tooltip_selectors = [
                "[class*='tooltip']", "[class*='Tooltip']", "[class*='popup']",
                "[class*='Popup']", "[role='tooltip']", "[class*='popper']"
            ]

            tooltip = None
            for selector in tooltip_selectors:
                try:
                    tooltips = driver.find_elements(By.CSS_SELECTOR, selector)
                    for t in tooltips:
                        if t.is_displayed() and "₽" in t.text and len(t.text) > 10:
                            tooltip = t
                            break
                except Exception:
                    continue
                if tooltip:
                    break

            if tooltip:
                text = tooltip.text.replace("\xa0", " ")
                text = re.sub(r"\s+", " ", text).strip()
                tokens = text.split(" ")

                i = 0
                while i < len(tokens):
                    if (
                            i + 2 < len(tokens)
                            and re.match(r"\d{1,2}", tokens[i])
                            and re.match(r"[А-Яа-я]+", tokens[i + 1])
                            and re.match(r"\d{4}", tokens[i + 2])
                    ):
                        date = f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}"
                        i += 3

                        num_parts = []
                        while i < len(tokens) and tokens[i].isdigit():
                            num_parts.append(tokens[i])
                            i += 1

                        if i < len(tokens) and tokens[i] == "₽":
                            price = int("".join(num_parts))
                            price_history.append({"date": date, "price": price})
                            i += 1

                    i += 1

                print(f"  ✓ История цен: {len(price_history)} записей")

            ActionChains(driver).move_by_offset(300, 300).perform()
            time.sleep(0.3)

        except Exception as e:
            print(f"  ✗ Ошибка истории цен: {e}")

        return price_history, screenshot_path

    def _take_top_screenshot(self, address_ad):

        try:
            driver = self.driver

            content_container = self._get_main_container()

            try:
                ads_selectors = [
                    "div[class*='item-view-ads']",
                    "div[class*='ads']",
                    "div[data-marker*='ads']"
                ]

                for selector in ads_selectors:
                    ads = content_container.find_elements(By.CSS_SELECTOR, selector)
                    for ad in ads:
                        self.driver.execute_script("arguments[0].remove();", ad)

            except Exception:
                pass

            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            full_path = ad_folder / "_tmp_full.png"
            driver.save_screenshot(str(full_path))

            rect = driver.execute_script("""
                            var r = arguments[0].getBoundingClientRect();
                            return {left:r.left, top:r.top, width:r.width, height:r.height};
                        """, content_container)

            dpr = driver.execute_script("return window.devicePixelRatio || 1;")

            left = int(rect["left"] * dpr)
            top = int(rect["top"] * dpr)
            right = int((rect["left"] + rect["width"]) * dpr)
            bottom = int((rect["top"] + rect["height"]) * dpr)

            img = Image.open(full_path)
            img_w, img_h = img.size

            # 🔧 защита от чёрных прямоугольников
            left = max(0, left)
            top = max(0, top)
            right = min(img_w, right)
            bottom = min(img_h, bottom)

            final_path = ad_folder / "титул.png"
            img.crop((left, top, right, bottom)).save(final_path)
            screenshot_path = str(final_path)

            full_path.unlink(missing_ok=True)

            return screenshot_path
        except:
            pass

    def _take_address_screenshot(self, address_ad):
        """Скриншот блока с картой"""
        try:
            driver = self.driver

            # Удаляем калькулятор ипотеки если есть
            try:
                mortgage_calc = driver.find_element(By.CSS_SELECTOR, "div#MortgageCalculatorNode")
                driver.execute_script("arguments[0].remove();", mortgage_calc)
                print("  ℹ Калькулятор ипотеки удалён")
                time.sleep(0.2)
            except Exception:
                pass

            # Ищем блок с картой
            map_element = driver.find_element(By.CSS_SELECTOR, "div[data-marker*='item-map-wrapper']").find_element(By.XPATH, "..")
            # Прокручиваем к карте
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});",
                map_element
            )
            time.sleep(0.3)

            # Получаем контейнер контента (для удаления рекламы)
            content_container = self._get_main_container()

            # Удаляем рекламу
            try:
                ads_selectors = [
                    "div[class*='item-view-ads']",
                    "div[class*='ads']",
                    "div[data-marker*='ads']"
                ]
                for selector in ads_selectors:
                    ads = content_container.find_elements(By.CSS_SELECTOR, selector)
                    for ad in ads:
                        driver.execute_script("arguments[0].remove();", ad)
            except Exception:
                pass

            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            # Делаем полный скриншот
            full_path = ad_folder / "_tmp_address.png"
            driver.save_screenshot(str(full_path))

            # Получаем координаты БЛОКА КАРТЫ (а не всего контейнера!)
            rect = driver.execute_script("""
                var r = arguments[0].getBoundingClientRect();
                return {left:r.left, top:r.top, width:r.width, height:r.height};
            """, map_element)

            dpr = driver.execute_script("return window.devicePixelRatio || 1;")

            left = int(rect["left"] * dpr)
            top = int(rect["top"] * dpr)
            right = int((rect["left"] + rect["width"]) * dpr)
            bottom = int((rect["top"] + rect["height"]) * dpr)

            img = Image.open(full_path)
            img_w, img_h = img.size

            # Защита от выхода за границы
            left = max(0, left)
            top = max(0, top)
            right = min(img_w, right)
            bottom = min(img_h, bottom)

            # Сохраняем обрезанный скриншот
            final_path = ad_folder / "адрес.png"
            img.crop((left, top, right, bottom)).save(final_path)
            screenshot_path = str(final_path)

            full_path.unlink(missing_ok=True)

            print(f"  ✓ Скриншот (адрес): {final_path.name}")
            return screenshot_path

        except Exception as e:
            print(f"  ✗ Ошибка скриншота адреса: {e}")
            return None

    def _take_bottom_screenshot(self, address_ad):
        """
        Скриншоты объявления:
        1) контейнер с описанием сверху
        2) если дата не видна — контейнер после прокрутки вниз
        Все скрины обрезаются по контейнеру контента
        """
        import time
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import NoSuchElementException
        from PIL import Image

        screenshots = []
        has_location_and_date = False
        try:
            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            driver = self.driver

            # ========================================
            # 1 Контейнер контента
            # ========================================
            content_container = self._get_main_container()

            # ========================================
            # 2 Удаляем рекламу (если есть)
            # ========================================
            try:
                ads_selectors = [
                    "div[class*='item-view-ads']",
                    "div[class*='ads']",
                    "div[data-marker*='ads']"
                ]
                for selector in ads_selectors:
                    ads = content_container.find_elements(By.CSS_SELECTOR, selector)
                    for ad in ads:
                        driver.execute_script("arguments[0].remove();", ad)
            except Exception:
                pass

            # ========================================
            # 3 Скролл к описанию
            # ========================================
            try:
                description = content_container.find_element(
                    By.XPATH,
                    ".//*[contains(@id,'item-description') or contains(@class,'item-view-description')]"
                )
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'start'});",
                    description
                )
            except NoSuchElementException:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'start'});",
                    content_container
                )
            time.sleep(0.5)

            # ========================================
            # 4 Скрин №1 — описание (через save+crop)
            # ========================================
            first_full_path = ad_folder / "_tmp_full.png"
            driver.save_screenshot(str(first_full_path))

            rect = driver.execute_script("""
                var r = arguments[0].getBoundingClientRect();
                return {left:r.left, top:r.top, width:r.width, height:r.height};
            """, content_container)

            dpr = driver.execute_script("return window.devicePixelRatio || 1;")

            left = int(rect["left"] * dpr)
            top = int(rect["top"] * dpr)
            right = int((rect["left"] + rect["width"]) * dpr)
            bottom = int((rect["top"] + rect["height"]) * dpr)

            img = Image.open(first_full_path)
            img_w, img_h = img.size

            left = max(0, left)
            top = max(0, top)
            right = min(img_w, right)
            bottom = min(img_h, bottom)

            first_cropped_path = ad_folder / "описание.png"
            img.crop((left, top, right, bottom)).save(first_cropped_path)
            screenshots.append(str(first_cropped_path))
            first_full_path.unlink(missing_ok=True)

            # ========================================
            # 5 Проверяем дату публикации
            # ========================================
            try:
                date_element = driver.find_element(
                    By.CSS_SELECTOR, "[data-marker='item-view/item-date']"
                )
                date_visible = driver.execute_script("""
                    var r = arguments[0].getBoundingClientRect();
                    return r.top >= 0 && r.bottom <= window.innerHeight;
                """, date_element)
            except NoSuchElementException:
                date_visible = True  # даты нет — второй скрин не нужен

            # ========================================
            # 5.1 Проверяем видимость h2 «Расположение» (скрин №1)
            # ========================================
            try:
                location_h2 = driver.find_element(
                    By.XPATH, "//h2[contains(text(), 'Расположение')]"
                )
                has_location_and_date = driver.execute_script("""
                    var r = arguments[0].getBoundingClientRect();
                    return r.top >= 0 && r.bottom <= window.innerHeight;
                """, location_h2)
            except NoSuchElementException:
                has_location_and_date = False

            # ========================================
            # 6 Если дата не видна — второй скрин
            # ========================================
            if not date_visible:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.5)

                second_full_path = ad_folder / "_tmp_full2.png"
                driver.save_screenshot(str(second_full_path))

                rect = driver.execute_script("""
                    var r = arguments[0].getBoundingClientRect();
                    return {left:r.left, top:r.top, width:r.width, height:r.height};
                """, content_container)

                dpr = driver.execute_script("return window.devicePixelRatio || 1;")

                left = int(rect["left"] * dpr)
                top = int(rect["top"] * dpr)
                right = int((rect["left"] + rect["width"]) * dpr)
                bottom = int((rect["top"] + rect["height"]) * dpr)

                img = Image.open(second_full_path)
                img_w, img_h = img.size

                left = max(0, left)
                top = max(0, top)
                right = min(img_w, right)
                bottom = min(img_h, bottom)

                second_cropped_path = ad_folder / "дата_публикации.png"
                img.crop((left, top, right, bottom)).save(second_cropped_path)
                screenshots.append(str(second_cropped_path))
                second_full_path.unlink(missing_ok=True)

            return screenshots, has_location_and_date

        except Exception as e:
            print(f"✗ Ошибка _take_bottom_screenshot: {e}")
            return screenshots, has_location_and_date

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

    def extract_price_per_m2(self, price_info: str):
        if not price_info:
            return None
        match = re.search(r'([\d\s]+)\s*₽', price_info)
        if match:
            try:
                if 'за сотку' in price_info:
                    return float(match.group(1).replace(" ", "")) / 100
                if 'за гектар' in price_info:
                    return float(match.group(1).replace(" ", "")) * 10000
                if 'в год' in price_info:
                    return float(match.group(1).replace(" ", "")) / 12
                return float(match.group(1).replace(" ", ""))
            except:
                pass
        return None

    def _remove_mortgage_calculator(self):
        """Удаляет калькулятор ипотеки со страницы"""
        try:
            mortgage_calc = self.driver.find_element(By.CSS_SELECTOR, "div#MortgageCalculatorNode")
            self.driver.execute_script("arguments[0].remove();", mortgage_calc)
            print("  ℹ Калькулятор ипотеки удалён")
            time.sleep(0.2)
        except Exception:
            pass

        except Exception as e:
            print(f"  ✗ Ошибка парсинга цены: {e}")
            return None, None
    @staticmethod
    async def _download_image(session, url, path):
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(path, 'wb') as f:
                        f.write(data)
                    return True
        except Exception as e:
            print(f"  ✗ Ошибка загрузки {url}: {e}")
        return False

    async def _download_all_images(self, image_urls, ad_folder):
        downloaded = set()
        async with aiohttp.ClientSession() as session:
            tasks = []
            for i, url in enumerate(image_urls):
                path = ad_folder / f"фото_{i + 1:03d}.jpg"
                tasks.append(self._download_image(session, url, path))
            results = await asyncio.gather(*tasks)
            for i, (url, ok) in enumerate(zip(image_urls, results)):
                if ok:
                    downloaded.add(url)
                    print(f"  ✓ Фото {i + 1}: загружено")
        return downloaded

    def _collect_and_download_images(self, address_ad):
        """Листает галерею, собирает src изображений, скачивает асинхронно"""
        from selenium.webdriver.common.by import By
        import time

        ad_folder = self.images_dir / str(address_ad)
        ad_folder.mkdir(parents=True, exist_ok=True)

        image_urls = []
        seen_urls = set()

        # Получаем первое изображение
        def get_current_src():
            try:
                wrapper = self.driver.find_element(
                    By.CSS_SELECTOR, "div[data-marker='image-frame/image-wrapper']"
                )
                img = wrapper.find_element(By.TAG_NAME, "img")
                src = img.get_attribute("src")
                return self._convert_to_max_quality(src) if src else None
            except Exception:
                pass
            try:
                img = self.driver.find_element(
                    By.CSS_SELECTOR, "#gallery-slider img"
                )
                src = img.get_attribute("src")
                return self._convert_to_max_quality(src) if src else None
            except Exception:
                return None

        # Листаем галерею
        max_images = 50
        no_new_count = 0

        for _ in range(max_images):
            src = get_current_src()
            if src and src not in seen_urls:
                seen_urls.add(src)
                image_urls.append(src)
                no_new_count = 0
            else:
                no_new_count += 1
                if no_new_count >= 3:
                    break  # Три подряд уже виденных — галерея прошла по кругу

            # Нажимаем кнопку "следующее фото"
            try:
                try:
                    btn = self.driver.find_element(
                        By.CSS_SELECTOR, "div[data-marker='image-frame/right-button']"
                    )
                except Exception:
                    btn = self.driver.find_element(
                        By.CSS_SELECTOR, "#gallery-slider button span[aria-label='Вперёд']"
                    )
                    btn = self.driver.execute_script("return arguments[0].closest('button');", btn)
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.3)
            except Exception:
                break

        print(f"  ✓ Найдено изображений: {len(image_urls)}")

        if not image_urls:
            return set()

        # Асинхронная загрузка
        downloaded = asyncio.run(self._download_all_images(image_urls, ad_folder))
        print(f"  ✓ Загружено: {len(downloaded)}/{len(image_urls)}")
        return downloaded

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

            getHistory = self._wait_for_page_load()
        getHistory = self._wait_for_page_load()

        self.driver.execute_script("document.body.style.zoom='80%'")
        self._remove_mortgage_calculator()

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

        price_text_el = self.driver.find_element(By.CSS_SELECTOR, "[id*='item-price-value']")
        price_text = self.driver.execute_script("return arguments[0].innerText;", price_text_el).replace('\xa0', ' ').replace('\n', ' ').strip()

        data["price_text"] = price_text
        data["price"], data["price_type"] = self._parse_price(price_text)

        # Дополнительная инфо о цене (за м², залог)
        # Вроде не работает
        p = self.driver.execute_script("""
            var container = arguments[0].closest('[data-marker="item-view/item-price-container"]');
            var parent = container;
            for (var i = 0; i < 5; i++) {
                parent = parent.parentElement;
                var p = parent.querySelector('p');
                if (p) return p;
            }
            return null;
        """, price_text_el)

        if p:
            price_info = self.driver.execute_script("return arguments[0].innerText;", p).replace('\xa0', ' ').strip()
        price_info = None
        if not price_info:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, "p")
                for el in elements:
                    text = self.driver.execute_script("return arguments[0].innerText;", el).replace('\xa0', ' ').strip()
                    if '₽' in text and any(x in text for x in ['м²', 'залог', 'сотку', 'в год', 'за гектар', 'за га']):
                        price_info = text
                        break
            except:
                pass
        data["price_info"] = price_info

        try:
            data["price_per_m2"] = self.extract_price_per_m2(data["price_info"])
        except:
            pass


        data["address"] = self._extract_text([
            "[data-marker='delivery/location']",
            "[itemprop='address']",
            ".style-item-address__string",
        ])

        split_address = data['address'].split('\n')
        address = ""

        for idx, s in enumerate(split_address):
            if 'мин.' not in s:
                address = address + s + " "
        data['address'] = address.strip()

        # История цен + скриншот с tooltip
        print("  Получение истории цен и скриншота...")
        print(f"getHist:{getHistory}")
        if getHistory:
            data["price_history"], top_screenshot = self._get_price_history_and_screenshot(data['title'] + data['address'].replace("\n", " "))
        else:
            top_screenshot = self._take_top_screenshot(data['title'] + data['address'].replace("\n", " "))

        data["description"] = self._extract_text([
            "[data-marker='item-view/item-description']",
            "[itemprop='description']",
            ".item-description-text",
        ])

        data["params"] = self._extract_params()

        area_match = re.search(r'(\d+[.,]?\d*)\s*м[²2]', data.get("title", "") + str(data.get("params", {})))
        if area_match:
            data["area_m2"] = float(area_match.group(1).replace(',', '.'))
        if data["params"].get("Общая площадь"):
            data["area_m2"] = float(data["params"].get("Общая площадь").replace('м²', '').strip())

        if data["params"].get("Площадь участка"):
            if 'сот.' in data["params"].get("Площадь участка"):
                data["params"]['Площадь участка'] = float(data["params"]['Площадь участка'].replace('сот.', '').strip()) * 100
            elif 'га' in data["params"].get("Площадь участка"):
                data["params"]['Площадь участка'] = float(
                    data["params"]['Площадь участка'].replace('сот.', '').strip()) * 10000
        if data["params"].get("Площадь"):
            if 'сот.' in data["params"].get("Площадь"):
                data["params"]["Площадь участка"] = float(data["params"]['Площадь'].replace('сот.', '').strip()) * 100
            elif 'га' in data["params"].get("Площадь"):
                data["params"]["Площадь участка"] = float(data["params"]['Площадь'].replace('сот.', '').strip()) * 10000

        if not data.get("area_m2"):
            sqr = data['params'].get("Площадь")
            if 'га' in sqr:
                data['area_m2'] = float(sqr.replace('га.', '').strip()) * 10000
            if 'сот.' in sqr:
                data['area_m2'] = float(sqr.replace('сот.', '').strip()) * 100

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
        if not data['price_per_m2'] and data.get('area_m2', False):
            data["price_per_m2"] = int(data["price"] / data["area_m2"])

        address_screenshot = self._take_address_screenshot(
            data['title'] + data['address'].replace("\n", " "))

        bottom_screenshot, has_location_and_date = self._take_bottom_screenshot(data['title'] + data['address'].replace("\n", " "))

        data["screenshots"] = {
            "top": top_screenshot,
            "bottom": bottom_screenshot,
            "address": address_screenshot
        }

        data["screenshots"]["has_location_and_date"] = has_location_and_date

        # Загрузка фотографий из галереи
        if self.download_photos:
            print("  Загрузка фотографий...")
            downloaded_images = self._collect_and_download_images(
                data['title'] + data['address'].replace("\n", " ")
            )
            data["images_count"] = len(downloaded_images)

        print(f"  ✓ Заголовок: {data.get('title', 'Не найден')[:50]}...")
        print(f"  ✓ Цена: {data.get('price', 'Не найдена')}")
        print(f"  ✓ Изображений: {data.get('images_count', 0)}")

        print(data)
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