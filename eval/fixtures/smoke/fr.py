"""French smoke fixtures: ``fr-smoke.jsonl`` (the French pack's, LAB-1774). Built by
``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005).

Phone numbers come from the blocks ``01 99 00 xx xx`` and ``06 39 98 xx xx``, which secondary
sources list as set aside for fiction in France (the EU gates ``eu/fr-*.jsonl`` use them too);
surnames are placeholder words (``Exemple``, ``Fictif``, ``Témoin``). Ids start with
``fr-pack-``: the EU gates the pack also lists already use ``fr-email-0001`` and the like.
"""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, A, E, P, iban

from pii_guard.eval import Document, from_markup
from pii_guard.languages.fr.checksums import nir_key, spi_check


def nir(payload13: str, grouped: bool = False) -> str:
    """A valid NIR from a made-up ``SAAMMDDCCCOOO`` (``2A``/``2B`` for Corsica)."""
    value = f"{payload13}{nir_key(payload13):02d}"
    if not grouped:
        return value
    parts = (value[0], value[1:3], value[3:5], value[5:7], value[7:10], value[10:13], value[13:])
    return " ".join(parts)


def bad_nir(payload13: str) -> str:
    """Looks like a NIR, fails the key."""
    return f"{payload13}{nir_key(payload13) % 97 + 1:02d}"


def spi(payload10: str, grouped: bool = False) -> str:
    """A valid numéro fiscal: ten made-up digits (the first 0-3) and their mod 511."""
    value = payload10 + spi_check(payload10)
    if not grouped:
        return value
    return " ".join((value[:2], value[2:4], value[4:7], value[7:10], value[10:]))


def fr_documents() -> list[Document]:
    iban_fr_1 = iban("FR", "12345000010001234567890")
    iban_fr_2 = iban("FR", "54321000020009876543210", grouped=False)
    nir_1 = nir("1850578006084", grouped=True)
    nir_2 = nir("2920369123045")
    nir_3 = nir("153072A073004", grouped=True)  # born in Corse-du-Sud
    spi_1, spi_2 = spi("2701234567", grouped=True), spi("1302345678")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "fr-pack-email-0001",
            f"Objet : Dépôt de garantie\n\nBonjour Madame {P('Claire Exemple')},\n\nnous "
            f"vous rembourserons le dépôt sur le compte {BANK(iban_fr_1)}. Pour toute "
            f"question, appelez le {PH('01 99 00 12 34')} ou écrivez à "
            f"{E('claire.exemple@example.fr')}.\n\nCordialement,\n{P('Jean Fictif')}",
            {"kind": "email"},
        ),
        (
            "fr-pack-contract-0002",
            "CONTRAT DE TRAVAIL\n\n"
            f"Entre {ORG('Société Imaginaire SAS')} et {P('Paul Modèle')}, né le "
            f"{DOB('14 mars 1985')}, demeurant {A('12 rue des Lilas, 69003 Lyon')}, numéro "
            f"de sécurité sociale {IDD(nir_1)}.\nLe salaire sera versé sur le compte "
            f"{BANK(iban_fr_2)}.",
            {"kind": "contract"},
        ),
        (
            "fr-pack-tax-0003",
            "AVIS D'IMPÔT SUR LE REVENU 2026\n"
            f"Déclarant 1 : {P('Sophie Essai')}, numéro fiscal : {IDD(spi_1)}\n"
            f"Adresse : {A('3 place de la République\n75011 Paris')}\n"
            "Montant à payer : 1 240,00 €, avant le 15.09.2026.",
            {"kind": "form"},
        ),
        (
            "fr-pack-letter-0004",
            f"{P('Luc Imaginaire')}\n"
            f"{A('13 bis avenue du Général de Gaulle\n13100 Aix-en-Provence')}\n\nMonsieur,\n\n"
            f"votre passeport n° {IDD('19ZZ00123')} est disponible en mairie. Contactez-nous au "
            f"{PH('01.99.00.45.67')}.\n\nVeuillez agréer nos salutations distinguées.\n"
            f"{ORG('Mairie de Fictiveville')}",
            {"kind": "letter"},
        ),
        (
            "fr-pack-chat-0005",
            f"salut c'est {P('Inès Témoin')} ! mon nouveau numéro c'est {PH('06 39 98 76 54')}, "
            f"sinon écris-moi sur {E('ines.temoin@example.net')}",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "fr-pack-elision-0006",
            f"C'est l'avis d'{P('Antoine Exemple')} : selon {P('Exemple')}, le dossier "
            f"d'{P('Hélène Fictif')} est complet. Le courrier pour l'{P('Ardent')} part demain.",
            {"kind": "note", "tags": ["elision"]},
        ),
        (
            "fr-pack-form-0007",
            "Formulaire de remboursement\n"
            f"Nom et prénom : {P('Marie Témoin')}\nDate de naissance : {DOB('03/02/1992')}\n"
            f"N° de sécurité sociale : {IDD(nir_2)}\n"
            f"Adresse : {A("5 impasse d'Alsace, 67000 Strasbourg")}\n"
            f"Permis de conduire n° {IDD('13AB00123')}\nTéléphone : {PH('0639980123')}",
            {"kind": "form"},
        ),
        (
            "fr-pack-bank-0008",
            f"Relevé de compte\nTitulaire : {P('Adam Fictif')}, numéro fiscal {IDD(spi_2)}\n"
            f"Carte bancaire n° {BANK('4111 1111 1111 1111')}, carte d'identité n° "
            f"{IDD('X4RTZZ123')}.\nSolde au 31.10.2026 : 3 456,78 €.",
            {"kind": "statement"},
        ),
        (
            "fr-pack-registry-0009",
            f"Enfant : {P('Zoé Modèle')}, née le {DOB('8 juillet 2002')} à Ajaccio. "
            f"NIR du représentant légal, {P('Pierre Modèle')} : {IDD(nir_3)}, "
            f"courriel {E('pierre.modele@example.org')}.",
            {"kind": "form"},
        ),
        (
            "fr-pack-negative-0010",
            "Compte rendu de la réunion du 01.02.2026\n"
            "Le salon a accueilli 20000 visiteurs en 18 mois. Numéro de commande "
            f"{bad_nir('1850578006084')}, facture n° {spi('2701234567')}, dossier "
            "RG 26/01234. La délibération n° 12/2026 attribue 500 000 000 € pour 2026-2030.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "fr-pack-negative-0011",
            "Le locataire et le bailleur fixent le loyer à 2 400 € par mois. À compter du "
            "01.01.2027, il augmentera de 2,5 %. L'appartement fait 54 m² au 4e étage, "
            "SIRET 123 456 789 00012, code produit 3012345678901.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="fr", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "fr-smoke.jsonl": fr_documents,
}
