"""Send refund notifications for the (fictional) bakery's support desk."""

import csv
import os
from dataclasses import dataclass
from pathlib import Path

SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@example.com")
API_BASE = "https://payments.example.com/v2/refunds"
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class Customer:
    id: int
    name: str
    email: str
    phone: str
    iban: str


def load_customers(path: str = "customers.csv") -> list[Customer]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [
            Customer(int(row["id"]), row["name"], row["email"], row["phone"], row["iban"])
            for row in csv.DictReader(handle)
        ]


def refund_message(customer: Customer, invoice_id: str) -> str:
    return (
        f"Dear {customer.name},\n\nwe refunded invoice {invoice_id} to {customer.iban}.\n"
        f"Questions? Write to {SUPPORT_EMAIL}.\n"
    )
