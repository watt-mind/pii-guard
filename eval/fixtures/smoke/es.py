"""Spanish smoke fixtures: ``es-smoke.jsonl`` (the Spanish pack's, LAB-1775). Built by
``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, A, E, P, iban, label

from pii_guard.eval import Document, from_markup
from pii_guard.languages.es.checksums import cif_control, dni_letter


def dni(payload8: str, layout: str = "compact") -> str:
    """A valid DNI from eight made-up digits: compact, ``-`` before the letter, or dotted."""
    letter = dni_letter(payload8)
    if layout == "hyphen":
        return f"{payload8}-{letter}"
    if layout == "dotted":
        return f"{payload8[:2]}.{payload8[2:5]}.{payload8[5:]}-{letter}"
    return payload8 + letter


def bad_dni(payload8: str) -> str:
    """Looks like a DNI, fails the check letter."""
    letters = "TRWAGMYFPDXBNJZSQVHLCKE"
    return payload8 + letters[(letters.index(dni_letter(payload8)) + 1) % 23]


def nie(prefix: str, payload7: str, sep: str = "") -> str:
    """A valid NIE ``X``/``Y``/``Z`` + seven made-up digits + the check letter."""
    letter = dni_letter(str("XYZ".index(prefix)) + payload7)
    return f"{prefix}{sep}{payload7}{sep}{letter}"


def cif(kind: str, payload7: str) -> str:
    """A valid CIF for a company limited by shares (``A``) or a limited company (``B``), which
    take a control digit."""
    return f"{kind}{payload7}{cif_control(payload7)}"


def es_documents() -> list[Document]:
    iban_es_1 = iban("ES", "21000418450200051332")
    iban_es_2 = iban("ES", "00491500051234567892", grouped=False)
    dni_1, dni_2 = dni("99000123"), dni("99000456", layout="hyphen")
    dni_3, dni_4 = dni("99000789", layout="dotted"), dni("99001234")
    nie_1, nie_2 = nie("X", "9000123"), nie("Y", "9000456", sep="-")
    cif_1 = cif("B", "9900012")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "es-email-0101",
            f"Asunto: Fianza del piso\n\nEstimada Sra. {P('Carmen Ejemplo Prueba')}:\n\nle "
            f"devolveremos la fianza en la cuenta {BANK(iban_es_1)}. Si tiene cualquier duda, "
            f"llame al {PH('612 345 678')} o escriba a {E('carmen.ejemplo@example.com')}.\n\n"
            f"Atentamente,\n{P('Sergio Ficticio Navas')}",
            {"kind": "email"},
        ),
        (
            "es-contract-0102",
            "CONTRATO DE COMPRAVENTA\n\n"
            f"Vendedor: {P('Javier Inventado Ruiz')}, DNI {IDD(dni_1)}, nacido el "
            f"{DOB('14/05/1976')}, con domicilio en {A('Calle Ficticia 14, 3.º B, 28012 Madrid')}"
            f".\nComprador: {ORG('Talleres Ejemplo S.L.')}, CIF {IDD(cif_1)}, "
            f"{A('Avenida del Puerto 51, 46021 Valencia')}.\n"
            f"El precio se abonará en la cuenta {BANK(iban_es_2)}.",
            {"kind": "contract"},
        ),
        (
            "es-invoice-0103",
            "FACTURA n.º FV-2026/0815\n"
            f"Cliente: {P('Tomás Supuesto Vidal')}, NIF {IDD(dni_2)}\n"
            f"Dirección: {A('Avda. de la Prueba 100, 41001 Sevilla')}\n"
            "Pedido n.º 70021834, importe total: 1.250,00 €, vencimiento 01/12/2026.",
            {"kind": "invoice"},
        ),
        (
            "es-letter-0104",
            f"{P('Katia Modelo Serrano')}\n{A('C/ Inventada 7, 2º izda.\n50001 Zaragoza')}\n\n"
            f"Estimada señora:\n\nle comunicamos que su tarjeta de residencia con NIE "
            f"{IDD(nie_1)} ya está lista para recoger. Para cualquier consulta, llame al "
            f"{PH('976 555 012')}.\n\nUn saludo,\n{ORG('Oficina de Extranjería de Zaragoza')}",
            {"kind": "letter"},
        ),
        (
            "es-chat-0105",
            f"hola!! soy {P('Lucía')} jaja, mi móvil nuevo es el {PH('623456789')}, escríbeme "
            f"también a {E('lucia.prueba@example.net')}",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "es-form-0106",
            "Solicitud de reembolso\n"
            f"Nombre y apellidos: {P('Eva Ficticia Morales')}\n"
            f"Fecha de nacimiento: {DOB('02/07/1992')}\nDNI: {IDD(dni_3)}\n"
            f"Domicilio: {A('Plaza Mayor 3, 37001 Salamanca')}\n"
            f"Pasaporte: {IDD('PAA000123')}\nTeléfono: {PH('+34 923 555 014')}",
            {"kind": "form"},
        ),
        (
            "es-bank-0107",
            f"Extracto de cuenta\nTitular: {P('Adam Ejemplar Ortiz')}, NIE {IDD(nie_2)}\n"
            f"Tarjeta de crédito n.º {label('PAYMENT_CARD', '4111 1111 1111 1111')}.\n"
            "Saldo final: 3.456,78 €.",
            {"kind": "statement"},
        ),
        (
            "es-names-0108",
            f"El contrato lo firmaron el Sr. {P('Prieto')} y la Sra. Dña. "
            f"{P('Marina Ejemplo Gil')}. Según {P('Ejemplo Gil')}, el Sr. {P('Prieto')} "
            f"entregó las llaves a {P('Raúl')} el lunes.",
            {"kind": "note", "tags": ["two-surnames", "title"]},
        ),
        (
            "es-medical-0109",
            f"Paciente: {P('Óscar Modelo Fuentes')}, nacido el {DOB('08/07/2002')}, DNI "
            f"{IDD(dni_4)}, n.º de la Seguridad Social {IDD('28 12345678 40')}.\n"
            f"Médico responsable: Dra. {P('Rocío Prueba Lara')}, "
            f"{E('r.prueba@example.org')}, tel. {PH('91 555 01 23')}.",
            {"kind": "form"},
        ),
        (
            "es-negative-0110",
            "Acta de la reunión del 01/02/2026\n"
            "En el estudio participaron 20000 personas durante 18 meses. Número de pedido "
            f"{dni('99000123')}, expediente 2026/004412, código de producto "
            f"{bad_dni('99000321')}. Por acuerdo n.º 12/2026 se aprobaron 500.000.000 € para "
            "los años 2026-2030.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "es-negative-0111",
            "El arrendatario pagará una renta de 950 € al mes. Desde el 01/01/2027 la renta "
            "subirá un 2,5 %. El piso tiene 3 habitaciones y 85 metros cuadrados, en la 4.ª "
            "planta. Referencia del pedido 612345678, factura 912345678.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="es", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "es-smoke.jsonl": es_documents,
}
