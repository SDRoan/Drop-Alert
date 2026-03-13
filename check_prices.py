import json
import os
import re
import smtplib
from collections import Counter
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Iterable, Optional

import gspread
import requests
from bs4 import BeautifulSoup

SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME") or "Trackers"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DropAlert/1.0; +https://github.com/)"
}
TIMEOUT_SECONDS = 20


def normalize_price(value: str) -> Optional[float]:
    if value is None:
        return None

    cleaned = re.sub(r"[^0-9,.-]", "", str(value)).strip()
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        number = float(cleaned)
    except ValueError:
        return None

    if number <= 0:
        return None

    return round(number, 2)


def ordered_unique(values: Iterable[float]) -> list[float]:
    seen = set()
    ordered = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def extract_price_from_html(html: str) -> Optional[float]:
    soup = BeautifulSoup(html, "html.parser")
    structured_candidates: list[float] = []

    selectors = [
        ('meta[itemprop="price"]', "content"),
        ('meta[property="product:price:amount"]', "content"),
        ('meta[name="twitter:data1"]', "content"),
    ]
    for selector, attr in selectors:
        for tag in soup.select(selector):
            price = normalize_price(tag.get(attr))
            if price is not None:
                structured_candidates.append(price)

    script_text = "\n".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
    script_patterns = [
        r'"price"\s*:\s*"?([0-9]+(?:[.,][0-9]{2})?)"?',
        r'"lowPrice"\s*:\s*"?([0-9]+(?:[.,][0-9]{2})?)"?',
        r'"priceAmount"\s*:\s*"?([0-9]+(?:[.,][0-9]{2})?)"?',
    ]
    for pattern in script_patterns:
        for match in re.findall(pattern, script_text, flags=re.IGNORECASE):
            price = normalize_price(match)
            if price is not None:
                structured_candidates.append(price)

    if structured_candidates:
        counts = Counter(structured_candidates)
        return counts.most_common(1)[0][0]

    text = soup.get_text(" ", strip=True)
    fallback_matches = re.findall(
        r'(?:\$|USD\s?)([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)',
        text,
        flags=re.IGNORECASE,
    )
    fallback_candidates = ordered_unique(
        price for price in (normalize_price(match) for match in fallback_matches) if price is not None
    )

    return fallback_candidates[0] if fallback_candidates else None


def fetch_current_price(url: str) -> Optional[float]:
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return extract_price_from_html(response.text)


def send_email(recipient: str, product_url: str, current_price: float, target_price: float) -> None:
    sender = os.environ["GMAIL_SMTP_EMAIL"]
    app_password = os.environ["GMAIL_SMTP_APP_PASSWORD"]

    message = EmailMessage()
    message["Subject"] = "DropAlert: Price Drop Detected!"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                "Your DropAlert target has been reached.",
                "",
                f"Product URL: {product_url}",
                f"Current price: ${current_price:.2f}",
                f"Target price: ${target_price:.2f}",
                "",
                "The product URL dropped to the current price which meets their target.",
            ]
        )
    )

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)


def open_worksheet():
    credentials = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    client = gspread.service_account_from_dict(credentials)
    spreadsheet = client.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    try:
        return spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=5)


def ensure_headers(worksheet) -> None:
    expected_headers = ["Email", "Product URL", "Target Price", "Current Price", "Date Added"]
    first_row = worksheet.row_values(1)
    if first_row[: len(expected_headers)] != expected_headers:
        worksheet.update("A1:E1", [expected_headers])


def process_rows() -> None:
    worksheet = open_worksheet()
    ensure_headers(worksheet)

    rows = worksheet.get_all_records()
    email_alerts_sent = 0

    for index, row in enumerate(rows, start=2):
        email = str(row.get("Email", "")).strip()
        product_url = str(row.get("Product URL", "")).strip()
        target_price = normalize_price(row.get("Target Price"))

        if not email or not product_url or target_price is None:
            continue

        try:
            current_price = fetch_current_price(product_url)
        except Exception as exc:
            print(f"[{index}] Failed to fetch {product_url}: {exc}")
            continue

        worksheet.update_cell(index, 4, current_price if current_price is not None else "")

        if current_price is None:
            print(f"[{index}] No price found for {product_url}")
            continue

        print(
            f"[{index}] Checked {product_url} | current=${current_price:.2f} | target=${target_price:.2f}"
        )

        if current_price <= target_price:
            try:
                send_email(email, product_url, current_price, target_price)
                email_alerts_sent += 1
                print(f"[{index}] Alert sent to {email}")
            except Exception as exc:
                print(f"[{index}] Failed to send alert to {email}: {exc}")

    print(
        json.dumps(
            {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "alerts_sent": email_alerts_sent,
            }
        )
    )


if __name__ == "__main__":
    process_rows()
