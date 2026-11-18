import argparse
import socket
from time import perf_counter
from typing import List, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REQUEST_COUNT = 10
CHUNK_SIZE = 64 * 1024
BYTES_PER_MB = 1_000_000
MAX_REQUEST_TIME_SECONDS = 600.0

DEFAULT_URL = (
    "https://images.wallpaperscraft.ru/image/single/bmw_avtomobil_belyj_218881_3840x2160.jpg"
)

HEADERS = {
    "User-Agent": "download-speed-test/1.0",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


class DownloadError(Exception):
    pass


def normalize_url(url: str) -> str:
    url = url.strip()

    if not url:
        return url

    if url.lower().startswith(("http://", "https://")):
        return url

    if url.startswith("//"):
        return "http:" + url

    return "http://" + url


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    if not parsed.netloc:
        return False

    if any(ch.isspace() for ch in url):
        return False

    try:
        hostname = parsed.hostname
    except ValueError:
        return False

    if not hostname:
        return False

    return True


def host_resolves(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        return False

    port = parsed.port

    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    try:
        socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        return True
    except (socket.gaierror, UnicodeError, ValueError, OSError):
        return False


def get_url_from_user_or_default(raw_url: str) -> str:
    raw_url = (raw_url or "").strip()

    while True:
        if raw_url:
            candidate = normalize_url(raw_url)

            if not is_valid_url(candidate):
                print(f"Некорректный URL: {raw_url}")
                raw_url = ""
                continue

            if not host_resolves(candidate):
                hostname = urlparse(candidate).hostname
                print(
                    f"Не удалось найти хост: {hostname}. "
                    "Проверьте адрес или нажмите Enter для значения по умолчанию."
                )
                raw_url = ""
                continue

            return candidate

        try:
            entered_url = input(
                "Вставьте URL картинки или используйте по умолчанию: "
            ).strip()
        except EOFError:
            print("\nВвод недоступен, использую URL по умолчанию.")
            candidate = normalize_url(DEFAULT_URL)

            if is_valid_url(candidate) and host_resolves(candidate):
                return candidate

            raise SystemExit(
                "URL по умолчанию недоступен: хост не найден. "
                "Проверьте подключение к интернету."
            )

        except KeyboardInterrupt:
            print("\nОтменено пользователем.")
            raise SystemExit(130)

        if not entered_url:
            candidate = normalize_url(DEFAULT_URL)

            if is_valid_url(candidate) and host_resolves(candidate):
                return candidate

            print(
                "URL по умолчанию недоступен: хост не найден. "
                "Введите другой адрес."
            )
            continue

        raw_url = entered_url


def download_once(url: str, timeout: float) -> Tuple[float, int]:
    request = Request(url, method="GET", headers=HEADERS)

    started = perf_counter()
    downloaded = 0

    limit = MAX_REQUEST_TIME_SECONDS

    effective_timeout = timeout
    if limit > 0:
        effective_timeout = min(timeout, limit)

    try:
        with urlopen(request, timeout=effective_timeout) as response:
            while True:
                elapsed_now = perf_counter() - started

                if limit > 0 and elapsed_now > limit:
                    raise DownloadError(
                        f"Запрос к {url} превысил лимит времени: "
                        f"{limit:.3f} s"
                    )

                chunk = response.read(CHUNK_SIZE)

                if not chunk:
                    break

                downloaded += len(chunk)

    except DownloadError:
        raise

    except HTTPError as exc:
        raise DownloadError(
            f"HTTP error {exc.code} for {url}: {exc.reason}"
        ) from exc

    except URLError as exc:
        elapsed_now = perf_counter() - started
        reason = str(exc.reason).lower()

        if limit > 0 and elapsed_now >= limit:
            raise DownloadError(
                f"Запрос к {url} превысил лимит времени: "
                f"{limit:.3f} s"
            ) from exc

        if "timed out" in reason:
            raise DownloadError(
                f"Превышено время ожидания данных от {url}: {exc.reason}"
            ) from exc

        if "getaddrinfo failed" in reason:
            raise DownloadError(
                f"Хост не найден: {url}. "
                "Проверьте домен или подключение к интернету."
            ) from exc

        raise DownloadError(
            f"Ошибка подключения к {url}: {exc.reason}"
        ) from exc

    except ValueError as exc:
        raise DownloadError(
            f"Некорректный URL: {url}. Ошибка: {exc}"
        ) from exc

    except OSError as exc:
        raise DownloadError(
            f"Сетевая ошибка при запросе к {url}: {exc}"
        ) from exc

    except Exception as exc:
        raise DownloadError(
            f"Запрос завершился ошибкой для {url}: {exc}"
        ) from exc

    elapsed = perf_counter() - started

    if limit > 0 and elapsed > limit:
        raise DownloadError(
            f"Запрос к {url} занял слишком много времени: "
            f"{elapsed:.3f} s > {limit:.3f} s"
        )

    return elapsed, downloaded


def run_speed_test(url: str, timeout: float) -> None:
    times: List[float] = []
    total_bytes = 0

    for index in range(1, REQUEST_COUNT + 1):
        elapsed, downloaded = download_once(url, timeout)

        times.append(elapsed)
        total_bytes += downloaded

        print(
            f"[{index}/{REQUEST_COUNT}] "
            f"time={elapsed:.3f}s "
            f"downloaded={downloaded / BYTES_PER_MB:.3f} MB"
        )

    total_time = sum(times)
    average_time = total_time / REQUEST_COUNT

    total_mb = total_bytes / BYTES_PER_MB
    speed_mb_s = total_mb / total_time if total_time > 0 else 0.0
    speed_mbit_s = speed_mb_s * 8

    print()
    print("Results:")
    print(f"  Requests:              {REQUEST_COUNT}")
    print(f"  Average request time:  {average_time:.3f} s")
    print(f"  Total downloaded:      {total_mb:.3f} MB")
    print(
        f"  Download speed:        "
        f"{speed_mb_s:.3f} MB/s ({speed_mbit_s:.3f} Mbit/s)"
    )


def ask_next_action() -> str:
    while True:
        print()
        print("Дальнейшие действия:")
        print("  1 — повторить проверку с этим же URL")
        print("  2 — ввести другой URL")
        print("  0 — выйти")

        try:
            choice = input(
                "Выберите действие (1/2/0): "
            ).strip().lower()
        except EOFError:
            return "exit"
        except KeyboardInterrupt:
            print("\nОтменено пользователем.")
            return "exit"

        if choice == "1":
            return "same"

        if choice == "2":
            return "new"

        if choice == "0":
            return "exit"

        print("Выбран неправильный пункт меню. Введите 1, 2 или 0.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Выполняет 10 последовательных GET-запросов к указанному URL, "
            "ждет полного ответа на каждый и печатает среднюю скорость скачивания."
        )
    )

    parser.add_argument(
        "url",
        nargs="?",
        default="",
        help=(
            "Адрес для проверки. Если не указан, скрипт запросит его у пользователя "
            "или использует URL по умолчанию."
        ),
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Таймаут одного запроса в секундах. По умолчанию: 30",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Выполнить одну проверку и завершиться без меню повтора.",
    )

    args = parser.parse_args()

    url = get_url_from_user_or_default(args.url)

    while True:
        try:
            run_speed_test(url, args.timeout)

        except DownloadError as exc:
            print(f"\nОшибка проверки: {exc}")

        except KeyboardInterrupt:
            print("\nПроверка прервана пользователем.")

        if args.once:
            break

        action = ask_next_action()

        if action == "exit":
            break

        if action == "new":
            url = get_url_from_user_or_default("")
            continue

        # action == "same" — просто повторяем цикл с текущим url


if __name__ == "__main__":
    main()