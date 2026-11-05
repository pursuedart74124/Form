import sys
import random
import threading
from time import sleep
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

# ===== ГЛОБАЛЬНЫЕ НАСТРОЙКИ =====

VOTES_PER_BROWSER = 5000
BROWSER_COUNT = 20
MAX_RESTARTS = 5
# ================================

FIO = ""
ClASS = ""

# XPath константы (исправлено: строки, а не set)
FIO_XPATH = "//input[@name='answer_short_text_9008993115518232']"
CLASS_XPATH = "//input[@name='answer_short_text_9008993115537632']"
SUBMIT_XPATH = "//button[@type='submit']"
RESUBMIT_XPATH = "//a[.//span[text()='Заполнить ещё раз']]"


def gen_random_numbers():
    """Генерирует случайное количество уникальных чисел от 1 до 19"""
    return random.sample(range(1, 20), random.randint(2, 5))


def create_driver():
    """Создает экземпляр драйвера с оптимизированными настройками"""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    # Автоматический подбор драйвера
    return webdriver.Chrome(options=options)


def vote_once(driver, wait):
    """Выполняет один цикл голосования"""
    wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')

    # Поле ФИО
    fio_input = wait.until(lambda d: d.find_element(By.XPATH, FIO_XPATH))
    fio_input.clear()
    fio_input.send_keys(FIO)

    # Поле Класс
    class_input = driver.find_element(By.XPATH, CLASS_XPATH)
    class_input.clear()
    class_input.send_keys(ClASS)

    # Отправляем
    driver.find_element(By.XPATH, SUBMIT_XPATH).click()

    # Ждем и ищем кнопку повторной отправки
    sleep(0.3)
    try:
        driver.find_element(By.XPATH, RESUBMIT_XPATH).click()
    except:
        driver.get(driver.current_url)

    sleep(0.2)


def format_time(seconds):
    """Форматирует время в читаемый вид"""
    if seconds < 60:
        return f"{seconds:.1f}с"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}м"
    else:
        return f"{seconds / 3600:.1f}ч"


def run_browser(url, index, votes_per_browser, stats, active_browsers, browser_lock, log_func):
    """Запускает браузер и выполняет указанное количество голосований с перезапуском при авариях"""
    driver = None
    votes_done = 0
    errors = 0
    restarts = 0
    max_restarts = MAX_RESTARTS

    # Регистрируем браузер как активный
    with browser_lock:
        active_browsers[index] = {
            'progress': 0,
            'status': 'starting',
            'votes_done': 0,
            'votes_total': votes_per_browser,
            'errors': 0,
            'restarts': 0,
            'start_time': datetime.now(),
            'last_update': datetime.now(),
            'thread_id': threading.current_thread().ident
        }

    # Основной цикл с перезапуском
    while votes_done < votes_per_browser and restarts <= max_restarts:
        driver = None
        try:
            driver = create_driver()
            driver.get(url)
            wait = WebDriverWait(driver, 30)

            with browser_lock:
                active_browsers[index]['status'] = 'running'
                active_browsers[index]['last_update'] = datetime.now()

            # Цикл голосования
            while votes_done < votes_per_browser:
                try:
                    vote_once(driver, wait)
                    votes_done += 1
                    stats['total'] += 1

                    percent = (votes_done / votes_per_browser) * 100
                    with browser_lock:
                        active_browsers[index]['progress'] = percent
                        active_browsers[index]['votes_done'] = votes_done
                        active_browsers[index]['last_update'] = datetime.now()
                        active_browsers[index]['errors'] = errors
                        active_browsers[index]['restarts'] = restarts

                except TimeoutException:
                    errors += 1
                    stats['errors'] += 1
                    with browser_lock:
                        active_browsers[index]['status'] = 'timeout'
                        active_browsers[index]['errors'] = errors

                    log_func(f"[Браузер {index:2d}] Таймаут #{errors}, обновление страницы...")
                    try:
                        driver.refresh()
                    except:
                        raise

                    sleep(0.5)
                    with browser_lock:
                        active_browsers[index]['status'] = 'running'

                except (WebDriverException, Exception) as e:
                    errors += 1
                    stats['errors'] += 1
                    with browser_lock:
                        active_browsers[index]['status'] = 'error'
                        active_browsers[index]['errors'] = errors

                    log_func(f"[Браузер {index:2d}] Ошибка #{errors}: {type(e).__name__}")
                    raise

            break

        except Exception as e:
            restarts += 1

            with browser_lock:
                active_browsers[index]['status'] = 'restarting'
                active_browsers[index]['restarts'] = restarts
                active_browsers[index]['last_update'] = datetime.now()

            if restarts <= max_restarts:
                log_func(f"[Браузер {index:2d}] Перезапуск #{restarts}/{max_restarts} "
                         f"(ошибка: {type(e).__name__}, прогресс: {votes_done}/{votes_per_browser})")
                sleep(2)
            else:
                log_func(f"[Браузер {index:2d}] 💀 Превышен лимит перезапусков ({max_restarts})! "
                         f"Потеряно голосов: {votes_per_browser - votes_done}")
                with browser_lock:
                    active_browsers[index]['status'] = 'crashed'
                    active_browsers[index]['progress'] = (votes_done / votes_per_browser) * 100
                break

        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            driver = None

    with browser_lock:
        elapsed = (datetime.now() - active_browsers[index]['start_time']).total_seconds()

        if votes_done >= votes_per_browser:
            active_browsers[index]['status'] = 'completed'
            active_browsers[index]['progress'] = 100
            active_browsers[index]['votes_done'] = votes_done
            stats['completed'] += 1
            log_func(f"✅ [Браузер {index:2d}] Завершено! "
                     f"Голосов: {votes_done}, Ошибок: {errors}, "
                     f"Перезапусков: {restarts}, Время: {format_time(elapsed)}")
        elif restarts > max_restarts:
            log_func(f"💀 [Браузер {index:2d}] Окончательная авария. "
                     f"Сделано: {votes_done}/{votes_per_browser}")


def get_browser_status_compact(info):
    """Формирует компактную строку статуса одного браузера"""
    status = info.get('status', 'unknown')
    progress = info.get('progress', 0)
    errors = info.get('errors', 0)
    restarts = info.get('restarts', 0)

    if status == 'running':
        icon = "●"
    elif status == 'completed':
        icon = "✓"
    elif status == 'timeout':
        icon = "⟳"
    elif status == 'error':
        icon = "⚠"
    elif status == 'restarting':
        icon = "↻"
    elif status == 'starting':
        icon = "◌"
    elif status == 'crashed':
        icon = "✕"
    else:
        icon = "○"

    # Прогресс-бар
    width = 10
    filled = int(width * progress / 100)
    bar = '█' * filled + '░' * (width - filled)

    extra = ""
    if restarts > 0:
        extra += f"R{restarts}"
    if errors > 0:
        extra += f"E{errors}"
    if extra:
        extra = f" {extra}"

    return f"{icon}{bar}{progress:5.1f}%{extra}"


def get_browsers_status(active_browsers, browser_lock):
    """Формирует строки со статусом браузеров по 3 в ряд"""
    with browser_lock:
        lines = []
        sorted_indices = sorted(active_browsers.keys())

        for i in range(0, len(sorted_indices), 3):
            group = sorted_indices[i:i + 3]
            row_parts = []

            for idx in group:
                info = active_browsers[idx]
                status_str = get_browser_status_compact(info)
                row_parts.append(f"[{idx:2d}] {status_str}")

            line = "  │  ".join(row_parts)
            lines.append(line)

        return "\n".join(lines)


def build_stats_text(stats, browser_count, votes_per_browser, start_time, active_browsers, browser_lock):
    """Формирует полный текст статистики в формате консоли"""
    elapsed = (datetime.now() - start_time).total_seconds()
    total_votes = browser_count * votes_per_browser

    with browser_lock:
        current_votes = stats['total']
        completed = stats['completed']
        errors = stats['errors']
        running_count = sum(1 for info in active_browsers.values()
                            if info.get('status') in ['running', 'timeout', 'error', 'restarting'])
        crashed_count = sum(1 for info in active_browsers.values()
                            if info.get('status') == 'crashed')

    percent = (current_votes / total_votes * 100) if total_votes > 0 else 0

    lines = []
    lines.append("=" * 95)
    lines.append("📊 СТАТИСТИКА")
    lines.append("=" * 95)
    lines.append(f"📊 Общий прогресс: {current_votes:,}/{total_votes:,} ({percent:.1f}%)")

    # Прогресс-бар 60 символов
    width = 60
    filled = int(width * percent / 100)
    bar = '█' * filled + '░' * (width - filled)
    lines.append(f"   {bar}")

    lines.append(f"✅ Завершено: {completed}  🔄 В процессе: {running_count}  "
                 f"💀 Аварий: {crashed_count}  ❌ Ошибок: {errors}")
    lines.append(f"⏱️  Время работы: {format_time(elapsed)}", )

    if elapsed > 0 and current_votes > 0:
        avg_speed = current_votes / elapsed
        lines[-1] += f"  ⚡ Скорость: {avg_speed:.1f} гол/с"
        if current_votes < total_votes:
            eta = (total_votes - current_votes) / avg_speed
            lines[-1] += f"  🕐 Осталось: {format_time(eta)}"

    lines.append("")
    lines.append("🖥️  Браузеры (по 3 в ряд):")
    lines.append(get_browsers_status(active_browsers, browser_lock))
    lines.append("")
    lines.append("   ● Работает  ✓ Готов  ⚠ Ошибка  ⟳ Таймаут  ↻ Перезапуск  ◌ Запуск  ✕ Авария")
    lines.append("   R=перезапуски  E=ошибки")
    lines.append("=" * 95)

    return "\n".join(lines)


class VotingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Система автоматического голосования v3.3")
        self.root.geometry("1000x750")
        self.root.configure(bg="#1e1e1e")

        self.stats = {'total': 0, 'completed': 0, 'errors': 0}
        self.active_browsers = {}
        self.browser_lock = threading.Lock()
        self.start_time = None
        self.running = False
        self.threads = []

        self._build_ui()

    def _build_ui(self):
        # Верхняя панель ввода
        input_frame = tk.Frame(self.root, bg="#1e1e1e", pady=10)
        input_frame.pack(fill=tk.X, padx=15)

        tk.Label(input_frame, text="ФИО:", bg="#1e1e1e", fg="#ffffff",
                 font=("Consolas", 12)).pack(side=tk.LEFT, padx=(0, 5))
        self.fio_entry = tk.Entry(input_frame, font=("Consolas", 12), width=23)
        self.fio_entry.pack(side=tk.LEFT, padx=(0, 20))
        self.fio_entry.insert(0, "")

        tk.Label(input_frame, text="Класс:", bg="#1e1e1e", fg="#ffffff",
                 font=("Consolas", 12)).pack(side=tk.LEFT, padx=(0, 5))
        self.class_entry = tk.Entry(input_frame, font=("Consolas", 12), width=2)
        self.class_entry.pack(side=tk.LEFT, padx=(0, 20))
        self.class_entry.insert(0, "")

        tk.Label(input_frame, text="Ссылка:", bg="#1e1e1e", fg="#ffffff",
                 font=("Consolas", 12)).pack(side=tk.LEFT, padx=(0, 5))
        self.URL = tk.Entry(input_frame, font=("Consolas", 12), width=40)
        self.URL.pack(side=tk.LEFT, padx=(0, 20))
        self.URL.insert(0, "")

        self.start_btn = tk.Button(input_frame, text="▶ СТАРТ", command=self.start_voting,
                                   bg="#2e7d32", fg="#ffffff", font=("Consolas", 12, "bold"),
                                   relief=tk.FLAT, padx=20, pady=4, cursor="hand2")
        self.start_btn.pack(side=tk.LEFT, padx=(10, 0))

        # Основное текстовое поле для статистики
        stats_frame = tk.Frame(self.root, bg="#1e1e1e")
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        self.stats_text = tk.Text(stats_frame, bg="#0d0d0d", fg="#00ff88",
                                  font=("Consolas", 10), wrap=tk.NONE,
                                  relief=tk.FLAT, insertbackground="#00ff88",
                                  state=tk.DISABLED)
        self.stats_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(stats_frame, command=self.stats_text.yview,
                                 bg="#1e1e1e", troughcolor="#0d0d0d")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stats_text.config(yscrollcommand=scrollbar.set)

        # Нижняя панель с логом
        log_frame = tk.Frame(self.root, bg="#1e1e1e")
        log_frame.pack(fill=tk.X, padx=15, pady=(0, 10))

        tk.Label(log_frame, text="Лог:", bg="#1e1e1e", fg="#888888",
                 font=("Consolas", 10)).pack(anchor=tk.W)

        self.log_text = tk.Text(log_frame, bg="#0d0d0d", fg="#ffcc00",
                                font=("Consolas", 9), height=6, wrap=tk.WORD,
                                relief=tk.FLAT, state=tk.DISABLED)
        self.log_text.pack(fill=tk.X)

    def log(self, msg):
        """Добавляет сообщение в лог (потокобезопасно через after)"""
        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _append)

    def update_stats_display(self):
        """Обновляет отображение статистики"""
        if not self.running:
            return

        text = build_stats_text(self.stats, BROWSER_COUNT, VOTES_PER_BROWSER,
                                self.start_time, self.active_browsers, self.browser_lock)

        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert("1.0", text)
        self.stats_text.config(state=tk.DISABLED)

        # Проверяем, все ли потоки завершились
        if all(not t.is_alive() for t in self.threads):
            self.running = False
            self.start_btn.config(state=tk.NORMAL, bg="#2e7d32")
            self.log("✅ Все браузеры завершили работу.")
            return

        self.root.after(1000, self.update_stats_display)

    def start_voting(self):
        global FIO, ClASS

        if self.running:
            return

        fio = self.fio_entry.get().strip()
        cl = self.class_entry.get().strip()
        URL = self.URL.get().strip()

        if not fio or not cl or not URL:
            messagebox.showerror("Ошибка", "Введите ФИО, класс и ссылку!")
            return

        FIO = fio
        ClASS = cl

        self.running = True
        self.start_btn.config(state=tk.DISABLED, bg="#555555")

        # Сброс статистики
        self.stats = {'total': 0, 'completed': 0, 'errors': 0}
        self.active_browsers = {}
        self.start_time = datetime.now()
        self.threads = []

        self.log(f"▶ Запуск: ФИО='{FIO}', Класс='{ClASS}'")
        self.log(f"   Браузеров: {BROWSER_COUNT}, Голосов на браузер: {VOTES_PER_BROWSER:,}")

        for i in range(BROWSER_COUNT):
            thread = threading.Thread(
                target=run_browser,
                args=(URL, i + 1, VOTES_PER_BROWSER, self.stats,
                      self.active_browsers, self.browser_lock, self.log),
                daemon=True
            )
            thread.start()
            self.threads.append(thread)
            sleep(0.2)

        self.update_stats_display()


def main():
    root = tk.Tk()
    app = VotingApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠ Прервано пользователем")
        sys.exit(1)