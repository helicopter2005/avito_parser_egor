"""
Cian Real Estate Parser
Парсер объявлений недвижимости с Циан используя Selenium

Установка зависимостей:
pip install selenium webdriver-manager requests pillow
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
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from PIL import Image


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(relative_path)


class CianParser:
    """Парсер объявлений недвижимости Циан"""

    def __init__(self, headless=False, download_images=True, images_dir="Скриншоты", slow_mode=False, on_captcha=None, on_auth=None):
        self.download_images = download_images
        self.images_dir = Path(images_dir)
        self.driver = None
        self.headless = headless
        self.slow_mode = slow_mode
        self.slow_delay = 0.4
        self.on_captcha = on_captcha
        self.on_auth = on_auth
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

    def _wait_for_page_load(self, timeout=30):
        """Ожидание загрузки страницы Циан"""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") in ["complete"]
            )
            time.sleep(0.5)
            return True
        except TimeoutException:
            print("  Таймаут загрузки страницы")
            return False

    def _check_authorization(self):
        """Проверка авторизации пользователя"""
        try:
            user_related = self.driver.find_element(By.CSS_SELECTOR, "[data-name='UserRelated']")
            if "Войти" in user_related.text:
                print("  ⚠ Требуется авторизация")
                return False
            return True
        except NoSuchElementException:
            # Элемент не найден - считаем что авторизован
            return True
        except Exception as e:
            print(f"  ℹ Ошибка проверки авторизации: {e}")
            return True

    def _expand_description(self):
        """Раскрытие полного описания, если есть кнопка 'Узнать больше'"""
        try:
            # Ищем кнопку раскрытия описания
            expand_button_selectors = [
                "span[data-id='toggle'][data-mark='ShutterToggle']",
                "span[data-mark='ShutterToggle']",
                "span[class*='toggle']",
                "[data-name='OfferCardDescription'] button",
                "[data-name='Description'] button"
            ]

            for selector in expand_button_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for button in buttons:
                        try:
                            if not button.is_displayed():
                                continue

                            button_text = button.text.lower()
                            # Проверяем текст кнопки
                            if 'узнать больше' in button_text or 'показать' in button_text:
                                # Скроллим к кнопке
                                self.driver.execute_script(
                                    "arguments[0].scrollIntoView({block: 'center'});",
                                    button
                                )
                                time.sleep(0.3)

                                # Кликаем через JavaScript
                                self.driver.execute_script("arguments[0].click();", button)
                                print("  ✓ Описание раскрыто")
                                time.sleep(0.5)
                                return True
                        except:
                            continue
                except:
                    continue

            print("  ℹ Кнопка раскрытия описания не найдена или не требуется")

        except Exception as e:
            print(f"  ℹ Ошибка при раскрытии описания: {e}")

        return False

    def _open_offer_stats(self):
        """Открытие статистики объявления для получения даты публикации"""
        try:
            # Ищем кнопку OfferStats
            stats_button_selectors = [
                "[data-name='OfferStats']",
                "button[data-name='OfferStats']",
                "[class*='offer-stats']",
                "[class*='OfferStats']"
            ]

            for selector in stats_button_selectors:
                try:
                    button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if button.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                        time.sleep(0.3)
                        button.click()
                        print("  ✓ Статистика объявления открыта")
                        time.sleep(1)
                        return True
                except:
                    continue

            print("  ℹ Кнопка статистики не найдена")
            return False
        except Exception as e:
            print(f"  ✗ Ошибка открытия статистики: {e}")
            return False

    def _take_top_screenshot_with_price_history(self, address_ad):
        """Скриншот верхней части страницы с наведением на историю цен (если есть)"""
        from selenium.webdriver.common.action_chains import ActionChains

        screenshot_path = None
        price_history = []

        try:
            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            # Скроллим к началу страницы
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)

            # Ищем заголовок и скроллим чуть выше
            try:
                title_selectors = [
                    "h1",
                    "[data-name='OfferTitle']",
                    "[class*='title']"
                ]

                title_element = None
                for selector in title_selectors:
                    try:
                        title_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if title_element.is_displayed():
                            break
                    except:
                        continue

                if title_element:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'}); window.scrollBy(0, -100);",
                        title_element
                    )
                    time.sleep(0.5)
            except:
                pass

            # Пытаемся найти и навести курсор на историю цен
            try:
                price_history_selectors = [
                    "[data-name='PriceHistory']",
                    "[class*='price-history']",
                    "[class*='PriceHistory']",
                    "button[data-name='PriceHistory']"
                ]

                hover_element = None
                for selector in price_history_selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for el in elements:
                            if el.is_displayed() and el.size["width"] > 0:
                                hover_element = el
                                break
                        if hover_element:
                            break
                    except:
                        continue

                if hover_element:
                    print("  ✓ История цен найдена, наводим курсор...")
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'}); window.scrollBy(0, -50);",
                        hover_element
                    )
                    time.sleep(0.3)
                    ActionChains(self.driver).move_to_element(hover_element).perform()
                    time.sleep(1.5)

                    # Пытаемся извлечь данные из tooltip
                    try:
                        tooltip_selectors = [
                            "[class*='tooltip']",
                            "[class*='Tooltip']",
                            "[role='tooltip']",
                            "[class*='popup']",
                            "[class*='Popup']"
                        ]

                        tooltip = None
                        for selector in tooltip_selectors:
                            tooltips = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            for t in tooltips:
                                if t.is_displayed() and ("₽" in t.text or "руб" in t.text):
                                    tooltip = t
                                    break
                            if tooltip:
                                break

                        if tooltip:
                            text = tooltip.text.replace("\xa0", " ")
                            text = re.sub(r"\s+", " ", text).strip()

                            lines = text.split("\n")
                            for line in lines:
                                date_match = re.search(r'(\d{1,2}\s+[а-яА-Я]+\s+\d{4})', line)
                                price_match = re.search(r'([\d\s]+)\s*[₽руб]', line)

                                if date_match and price_match:
                                    date = date_match.group(1)
                                    price = int(price_match.group(1).replace(" ", ""))
                                    price_history.append({"date": date, "price": price})

                            if price_history:
                                print(f"  ✓ История цен: {len(price_history)} записей")

                    except Exception as e:
                        print(f"  ℹ Не удалось извлечь историю цен из tooltip: {e}")
                else:
                    print("  ℹ История цен не найдена")

            except Exception as e:
                print(f"  ℹ Ошибка при поиске истории цен: {e}")

            # Ищем контейнер контента - только OfferCardPageLayout
            content_container = None
            try:
                content_container = self.driver.find_element(By.CSS_SELECTOR, "[data-name='OfferCardPageLayout']")
                if not content_container.is_displayed() or content_container.size['width'] < 100:
                    content_container = None
            except:
                content_container = None

            if not content_container:
                print("  ⚠ Контейнер OfferCardPageLayout не найден, используем весь скриншот")

            # Делаем скриншот
            full_path = ad_folder / "_tmp_top.png"
            self.driver.save_screenshot(str(full_path))

            img = Image.open(full_path)
            img_w, img_h = img.size

            if content_container:
                rect = self.driver.execute_script("""
                    var r = arguments[0].getBoundingClientRect();
                    return {left:r.left, top:r.top, width:r.width, height:r.height};
                """, content_container)

                dpr = self.driver.execute_script("return window.devicePixelRatio || 1;")

                left = int(rect["left"] * dpr)
                top = int(rect["top"] * dpr)
                width = int(rect["width"] * dpr)
                height = int(rect["height"] * dpr)

                right = left + width
                bottom = top + height

                # Корректируем координаты с проверками
                left = max(0, min(left, img_w - 1))
                top = max(0, min(top, img_h - 1))
                right = max(left + 1, min(right, img_w))
                bottom = max(top + 1, min(bottom, img_h))

                # Дополнительная проверка
                if right <= left or bottom <= top or width < 100 or height < 100:
                    print(f"  ⚠ Некорректные размеры контейнера, используем весь скриншот")
                    final_path = ad_folder / "титул.png"
                    img.save(final_path)
                else:
                    final_path = ad_folder / "титул.png"
                    img.crop((left, top, right, bottom)).save(final_path)
            else:
                final_path = ad_folder / "титул.png"
                img.save(final_path)

            screenshot_path = str(final_path)
            full_path.unlink(missing_ok=True)

            print(f"  ✓ Скриншот верхней части: {final_path.name}")

            # Убираем курсор
            try:
                ActionChains(self.driver).move_by_offset(300, 300).perform()
                time.sleep(0.3)
            except:
                pass

            return screenshot_path, price_history

        except Exception as e:
            print(f"  ✗ Ошибка верхнего скриншота: {e}")
            return None, []

    def _take_publication_date_screenshot(self, address_ad):
        """Скриншот даты публикации (после открытия OfferStats)"""
        try:
            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            # Открываем статистику
            self._open_offer_stats()

            # Ищем контейнер со статистикой/датой
            stats_selectors = [
                "[data-name='OfferStats']",
                "[class*='offer-stats']",
                "[class*='statistics']"
            ]

            stats_element = None
            for selector in stats_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed() and el.size["width"] > 0:
                            stats_element = el
                            break
                    if stats_element:
                        break
                except:
                    continue

            if stats_element:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});",
                    stats_element
                )
                time.sleep(0.5)

            # Ищем контейнер контента - только OfferCardPageLayout
            content_container = None
            try:
                content_container = self.driver.find_element(By.CSS_SELECTOR, "[data-name='OfferCardPageLayout']")
                if not content_container.is_displayed() or content_container.size['width'] < 100:
                    content_container = None
            except:
                content_container = None

            if not content_container:
                print("  ⚠ Контейнер OfferCardPageLayout не найден, используем весь скриншот")

            # Делаем скриншот
            full_path = ad_folder / "_tmp_date.png"
            self.driver.save_screenshot(str(full_path))

            img = Image.open(full_path)
            img_w, img_h = img.size

            if content_container:
                rect = self.driver.execute_script("""
                    var r = arguments[0].getBoundingClientRect();
                    return {left:r.left, top:r.top, width:r.width, height:r.height};
                """, content_container)

                dpr = self.driver.execute_script("return window.devicePixelRatio || 1;")

                left = int(rect["left"] * dpr)
                top = int(rect["top"] * dpr)
                width = int(rect["width"] * dpr)
                height = int(rect["height"] * dpr)

                right = left + width
                bottom = top + height

                left = max(0, min(left, img_w - 1))
                top = max(0, min(top, img_h - 1))
                right = max(left + 1, min(right, img_w))
                bottom = max(top + 1, min(bottom, img_h))

                if right <= left or bottom <= top or width < 100 or height < 100:
                    print(f"  ⚠ Некорректные размеры контейнера, используем весь скриншот")
                    final_path = ad_folder / "дата_публикации.png"
                    img.save(final_path)
                else:
                    final_path = ad_folder / "дата_публикации.png"
                    img.crop((left, top, right, bottom)).save(final_path)
            else:
                final_path = ad_folder / "дата_публикации.png"
                img.save(final_path)

            screenshot_path = str(final_path)
            full_path.unlink(missing_ok=True)

            print(f"  ✓ Скриншот даты публикации: {final_path.name}")

            # Закрываем окно статистики на крестик
            try:
                close_button_selectors = [
                    "div[role='button'][aria-label='Закрыть']",
                    "div[class*='close'][role='button']",
                    "button[aria-label='Закрыть']",
                    "[aria-label='Закрыть']"
                ]

                for selector in close_button_selectors:
                    try:
                        close_buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for btn in close_buttons:
                            if btn.is_displayed():
                                self.driver.execute_script("arguments[0].click();", btn)
                                print("  ✓ Окно статистики закрыто")
                                time.sleep(0.3)
                                return screenshot_path
                    except:
                        continue

            except Exception as e:
                print(f"  ℹ Не удалось закрыть окно статистики: {e}")

            return screenshot_path

        except Exception as e:
            print(f"  ✗ Ошибка скриншота даты: {e}")
            return None

    def _take_description_screenshot(self, address_ad):
        """Скриншот описания: 1 скрин или 2 (верх/низ), если не влезает в viewport"""
        try:
            ad_folder = self.images_dir / str(address_ad)
            ad_folder.mkdir(parents=True, exist_ok=True)

            # Раскрываем описание
            self._expand_description()

            # Ищем блок описания
            description_selectors = [
                "[data-name='Description']",
                "[data-name='OfferCardDescription']",
                "[class*='description']",
                "[class*='Description']"
            ]

            description_element = None
            for selector in description_selectors:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if el.is_displayed() and el.size["height"] > 50:
                        description_element = el
                        break
                except:
                    continue

            if not description_element:
                print("  ⚠ Блок описания не найден")
                return None

            # Центрируем описание в viewport
            self.driver.execute_script("""
                var r = arguments[0].getBoundingClientRect();
                var vh = window.innerHeight;
                window.scrollBy(0, r.top - (vh / 2) + (r.height / 2));
            """, description_element)
            time.sleep(0.5)

            # Размеры description и viewport
            desc_metrics = self.driver.execute_script("""
                var r = arguments[0].getBoundingClientRect();
                return { height: r.height, top: r.top, bottom: r.bottom };
            """, description_element)

            viewport_height = self.driver.execute_script("return window.innerHeight;")
            need_two_screens = desc_metrics["height"] > viewport_height * 0.9

            # Ищем контейнер страницы
            content_container = None
            try:
                cc = self.driver.find_element(By.CSS_SELECTOR, "[data-name='OfferCardPageLayout']")
                if cc.is_displayed() and cc.size["width"] > 100:
                    content_container = cc
            except:
                pass

            if not content_container:
                print("  ⚠ Контейнер OfferCardPageLayout не найден, используем весь скриншот")

            screenshots = []

            def make_screenshot(name):
                path = ad_folder / name
                self.driver.save_screenshot(str(path))
                return path

            if not need_two_screens:
                screenshots.append(make_screenshot("_tmp_desc_1.png"))
            else:
                # --- скрин 1: верх описания ---
                self.driver.execute_script("""
                    var r = arguments[0].getBoundingClientRect();
                    window.scrollBy(0, r.top - window.innerHeight * 0.1);
                """, description_element)
                time.sleep(0.4)
                screenshots.append(make_screenshot("_tmp_desc_1.png"))

                # --- скрин 2: низ описания ---
                self.driver.execute_script("""
                    var r = arguments[0].getBoundingClientRect();
                    window.scrollBy(0, r.bottom - window.innerHeight * 0.9);
                """, description_element)
                time.sleep(0.4)
                screenshots.append(make_screenshot("_tmp_desc_2.png"))

            result_paths = []

            for idx, full_path in enumerate(screenshots, start=1):
                img = Image.open(full_path)
                img_w, img_h = img.size

                if content_container:
                    rect = self.driver.execute_script("""
                        var r = arguments[0].getBoundingClientRect();
                        return {left:r.left, top:r.top, width:r.width, height:r.height};
                    """, content_container)

                    dpr = self.driver.execute_script("return window.devicePixelRatio || 1;")

                    left = int(rect["left"] * dpr)
                    top = int(rect["top"] * dpr)
                    right = int((rect["left"] + rect["width"]) * dpr)
                    bottom = int((rect["top"] + rect["height"]) * dpr)

                    left = max(0, min(left, img_w - 1))
                    top = max(0, min(top, img_h - 1))
                    right = max(left + 1, min(right, img_w))
                    bottom = max(top + 1, min(bottom, img_h))

                    name = "описание.png" if len(screenshots) == 1 else f"описание_{idx}.png"
                    final_path = ad_folder / name

                    if right > left and bottom > top:
                        img.crop((left, top, right, bottom)).save(final_path)
                    else:
                        img.save(final_path)
                else:
                    name = "описание.png" if len(screenshots) == 1 else f"описание_{idx}.png"
                    final_path = ad_folder / name
                    img.save(final_path)

                result_paths.append(str(final_path))
                full_path.unlink(missing_ok=True)

            if len(result_paths) == 1:
                print("  ✓ Описание влезло — 1 скриншот")
                return result_paths[0]
            else:
                print("  ✓ Описание длинное — 2 скриншота")
                return result_paths

        except Exception as e:
            print(f"  ✗ Ошибка скриншота описания: {e}")
            import traceback
            traceback.print_exc()
            return None

    def continue_after_captcha(self):
        self._wait_for_user = False

    def _slow_pause(self, message=""):
        if self.slow_mode:
            if message:
                print(f"  [SLOW MODE] {message}")
            time.sleep(self.slow_delay)

    def _extract_text(self, selectors, default=""):
        """Извлечение текста по списку селекторов"""
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
        """Парсинг цены из текста"""
        if not price_text:
            return None, None

        # Извлекаем числа
        numbers = re.findall(r'[\d\s]+', price_text)
        if numbers:
            price_str = numbers[0].replace(' ', '').replace('\xa0', '')
            try:
                price = int(price_str)
            except ValueError:
                price = None
        else:
            price = None

        # Определяем тип цены
        price_type = "месяц"
        if "м²" in price_text or "м2" in price_text:
            price_type = "м²/месяц"
        elif "год" in price_text:
            price_type = "год"
            try:
                price /= 12
            except:
                pass

        return price, price_type

    def _extract_num(self, text):
        text = text.replace("²", "")
        num = ""
        for i, c in enumerate(text):
            if c.isdigit():
                num += c
            elif i != 0 and text[i-1].isdigit() and c == '.':
                num += c
        return float(num)

    def _parse_price_per_m2(self):
        try:
            items = self.driver.find_elements(By.CSS_SELECTOR, "[data-name='OfferFactItem']")

            for item in items:
                title = item.find_element(By.TAG_NAME, "span").text.strip()
                value = item.find_elements(By.TAG_NAME, "span")[1].text.strip()
                if "Цена за метр" in title:
                    if 'в год' in value:
                        value = self._extract_num(value) / 12
                    elif "в месяц" in value:
                        value = self._extract_num(value)
                    else:
                        value = float(value.replace("₽/м²", "").replace("₽", "").replace(" ", ""))
                    return value
                elif "Цена за сотку" in title:
                    value = self._extract_num(value)
                    return value / 100
                elif "Цена за гектар" in title:
                    value = self._extract_num(value)
                    return value / 10000

            return None

        except Exception as e:
            print(str(e))
            return None

    def _extract_params(self):
        """Извлечение параметров объявления"""
        params = {}

        try:
            param_selectors = [
                "[data-name*='ObjectFactoids'] div",
                "[class*='features'] li",
                "[class*='offer-card-params'] li",
                "[data-name='OfferCardFeatures'] li"
            ]

            for selector in param_selectors:
                try:
                    param_items = self.driver.find_elements(By.CSS_SELECTOR, selector)

                    for item in param_items:
                        text = item.text.strip()
                        if ':' in text:
                            key, value = text.split(':', 1)
                            params[key.strip()] = value.strip()
                        elif '\n' in text:
                            parts = text.split('\n')
                            if len(parts) >= 2:
                                params[parts[0].strip()] = parts[1].strip()

                    if params:
                        break
                except:
                    continue
        except Exception as e:
            print(f"  ℹ Не удалось извлечь параметры: {e}")

        return params

    def parse_ad(self, url):
        """Парсинг одного объявления"""
        if not self.driver:
            self._setup_driver()

        print(f"\nПарсинг: {url}")

        self.driver.get(url)

        # Проверяем наличие капчи или блокировки
        page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()

        if any(phrase in page_text for phrase in [
            "страница не найдена",
            "объявление не найдено",
            "не существует"
        ]):
            return {
                "url": url,
                "page_not_found": True
            }

        is_blocked = any(phrase in page_text for phrase in [
            "подтвердите, что вы не робот",
            "доступ ограничен",
            "заблокирован",
            "access denied",
            "проверка безопасности",
            "captcha"
        ])

        # Проверяем наличие основного контента
        try:
            self.driver.find_element(By.CSS_SELECTOR, "h1, [data-name='OfferTitle']")
            has_content = True
        except:
            has_content = False

        if is_blocked or not has_content:
            self._wait_for_user = True

            if self.on_captcha:
                self.on_captcha()

            while self._wait_for_user:
                time.sleep(0.3)

        # Ждем загрузки страницы
        self._wait_for_page_load()

        if not self._check_authorization():
            self._wait_for_user = True

            if self.on_captcha:
                # ЗАМЕНЯЕМ НА:
                if hasattr(self, 'on_auth') and self.on_auth:
                    self.on_auth()
                else:
                    self.on_captcha()

            while self._wait_for_user:
                time.sleep(0.3)

        # Уменьшаем масштаб для лучших скриншотов
        self.driver.execute_script("document.body.style.zoom='80%'")
        time.sleep(0.5)

        # Инициализируем данные
        data = {
            "url": url,
            "parsed_at": datetime.now().isoformat(),
        }

        # Заголовок
        data["title"] = self._extract_text([
            "h1[data-name='OfferTitle']",
            "h1",
            "[class*='title']"
        ])

        # Цена - извлекаем из div data-name=PriceInfo
        price_text = self._extract_text([
            "[data-name='PriceInfo']",
            "[data-name='OfferPrice']",
            "[class*='price-value']",
            "[class*='price']",
            "[itemprop='price']"
        ])

        data["price_text"] = price_text
        data["price"], data["price_type"] = self._parse_price(price_text)

        price_per_m2 = self._parse_price_per_m2()
        if price_per_m2:
            data["price_per_m2"] = price_per_m2

        # Адрес
        data["address"] = self._extract_text([
            "[data-name='Geo']",
            "[data-name='Address']",
            "[itemprop='address']",
            "[class*='address']"
        ])

        # Очищаем адрес от лишних строк
        if data["address"]:
            data["address"] = data["address"].split("На карте")[0].strip()

        # Создаем идентификатор для папки скриншотов
        screenshot_id = (data.get('title', '') + data.get('address', '')).replace("\n", " ").strip()

        # Скриншот 1: Верхняя часть с историей цен (если есть)
        print("  Получение верхнего скриншота...")
        top_screenshot, price_history = self._take_top_screenshot_with_price_history(screenshot_id)

        # Скриншот 2: Дата публикации
        print("  Получение скриншота даты публикации...")
        date_screenshot = self._take_publication_date_screenshot(screenshot_id)

        # Скриншот 3: Описание
        print("  Получение скриншота описания...")
        description_screenshot = self._take_description_screenshot(screenshot_id)

        # Сохраняем пути к скриншотам
        data["screenshots"] = {
            "top": top_screenshot,
            "publication_date": date_screenshot,
            "description": description_screenshot
        }

        # Описание
        data["description"] = self._extract_text([
            "[data-name='Description']",
            "[data-name='OfferCardDescription']",
            "[itemprop='description']",
            "[class*='description-text']"
        ]).replace("Свернуть", "").strip()

        # Параметры
        data["params"] = self._extract_params()

        # Пытаемся найти площадь в параметрах
        for key in ["Общая площадь", "Площадь", "Площадь дома"]:
            if data["params"].get(key):
                try:
                    area_text = data["params"][key]
                    area_value = float(re.search(r'(\d+[.,]?\d*)', area_text).group(1).replace(',', '.'))
                    data["area_m2"] = area_value
                    break
                except:
                    pass
        if data["params"].get("Площади"):
            try:
                area_text = data["params"]['Площади']
                area_value = self._extract_num(area_text.split('–')[0])
                data["area_m2"] = area_value
            except:
                pass


        # Извлекаем этаж
        if data["params"].get("Этаж"):
            data["params"]["Этаж"] = data["params"]["Этаж"].split('из')[0].strip()

        # Площадь участка
        for key in ["Площадь участка", "Участок"]:
            if data["params"].get(key):
                try:
                    if 'сот' in data["params"].get(key):
                        data["params"]["Площадь участка"] = float(
                            data["params"].get(key).replace("сот.", '').replace(',', '.').strip()) * 100
                    elif 'га' in data["params"].get(key):
                        data["params"]["Площадь участка"] = float(
                            data["params"].get(key).replace("га", '').replace(',', '.').strip()) * 10000
                    break
                except:
                    pass

        # Материал стен
        if data["params"].get("Материал дома"):
            data["params"]["Материал стен"] = data["params"]["Материал дома"]

        # Дата публикации
        data["published_date"] = self._extract_text([
            "[data-name='PublicationDate']",
            "[class*='publication-date']",
            "[class*='offer-date']"
        ])

        # Если цена указана за м², пересчитываем
        if "м²" in data.get("price_text", "").lower() and data.get("area_m2"):
            if data["price"]:
                data["price"] = round(data["price"] * data["area_m2"], 1)

        print(f"  ✓ Заголовок: {data.get('title', 'Не найден')[:50]}...")
        print(f"  ✓ Цена: {data.get('price', 'Не найдена')}")
        print(f"  ✓ Адрес: {data.get('address', 'Не найден')[:50]}...")

        print(data)
        return data

    def parse_multiple(self, urls):
        """Парсинг нескольких объявлений"""
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

    def save_results(self, results, filename="cian_results.json"):
        """Сохранение результатов в JSON"""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nРезультаты сохранены в {filename}")

    def close(self):
        """Закрытие браузера"""
        if self.driver:
            self.driver.quit()
            self.driver = None