"""pl-pii-bench v1.0.0: synthetic, exhaustively annotated Polish documents (LAB-1392).

`pl-pii-bench/pl-pii-bench <https://huggingface.co/datasets/pl-pii-bench/pl-pii-bench>`_
(data CC-BY-4.0, "pl-pii-bench, version 1.0.0, Anonimator, CC BY 4.0"): complete synthetic
Polish administrative documents (invoices, tax returns, employment contracts, bank statements,
court judgments, registry extracts), every identifier synthetic and checksum-valid, plus a
negative lane of same-shape values whose check digits fail. Its card says it is an evaluation
set and asks that nobody train on it; the decontamination gate (``training/ner/decontam.py``)
holds pii-guard to that.

Five of its seven public lanes are used, every document of each: ``core`` (33 full
documents), ``identifiers`` (12), ``address`` (14), ``negative`` (14, no gold spans: they
measure over-masking only) and ``inflection`` (273 one-sentence rows, a name in each of the
seven grammatical cases). ``robustness`` (perturbed copies of the ``core`` documents) and
``pdf`` (re-extracted ``core`` documents) are left out: they are near-duplicates of ``core``.

Label mapping: PESEL, ID card (``DOWOD``), passport, driving licence and NIP (a tax number;
a sole trader's NIP is personal) are ``ID_DOCUMENT``; IBAN and payment card numbers are
``BANK_ACCOUNT``; ``ORG`` is ``ORGANIZATION`` (a ``keep`` type). REGON (a business
register number) and VIN (a vehicle) have no pii-guard type: ignore regions. A street
(``LOC`` with a digit), merged with its postcode and town, is ``ADDRESS``; a town or an
administrative unit on its own (``LOC`` without a digit) and a postcode on its own are ignore
regions, as in every other set.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets._common import LabelMap, Row
from pii_guard.eval.datasets.spec import Dataset, SourceFile
from pii_guard.types import EntityType

__all__ = ["DATASET", "LABELS", "rows"]

REPO = "pl-pii-bench/pl-pii-bench"
REVISION = "bef947d33bc37ec3f8f759ba251bf27208de239f"

#: (path in the source repository, SHA-256), from its ``dataset-manifest.json`` at REVISION.
FILES: tuple[tuple[str, str], ...] = (
    (
        "data/core/core-deklaracja-pit-high.json",
        "a1a83a3fd96cc161ad59286a6531547fb0abaf64b5ca08d883f596c0fad312e3",
    ),
    (
        "data/core/core-deklaracja-pit-low.json",
        "25e525decd7ecba35301539f017da028a425a897224b7e1e963e58d6d18d8cfa",
    ),
    (
        "data/core/core-deklaracja-pit-medium.json",
        "379f15a4aa58241b8447669e11ce03c0ab60f4b643fbdc05102ef797808f2738",
    ),
    (
        "data/core/core-faktura-vat-high-alt1.json",
        "96ee4f2e75b47e888f941d32d369d28f84b064f4784f3985752e9370070dd5f9",
    ),
    (
        "data/core/core-faktura-vat-high.json",
        "f75887e6e39f9fcc656259ac450c3e04f2f6cbff9660daacf8a23304565a8044",
    ),
    (
        "data/core/core-faktura-vat-low.json",
        "3629908de8139af24602af39d6cfd3c9ba4d66b68e77a6b2bac4dbb26c508632",
    ),
    (
        "data/core/core-faktura-vat-medium.json",
        "8ceaac6bc4f6cc1759616f0fa0ce5017bfbde30093e09eaf40d31398d7bb6ff6",
    ),
    (
        "data/core/core-kpir-ledger-high-alt1.json",
        "889dc59f95bcc20b89a18cd0d234be12bb16a0ae2a9b7232c5670ff4279f68d4",
    ),
    (
        "data/core/core-kpir-ledger-high.json",
        "5d576e7f08532fd0b34ab94ecd48f3894bcc73aff35971bbb1d2a0594a4ac753",
    ),
    (
        "data/core/core-kpir-ledger-low.json",
        "53824191257886eda8463a24e8f533b59652225fb73e14f6432dbcc24cc76dad",
    ),
    (
        "data/core/core-kpir-ledger-medium.json",
        "d50b1f0e2665089a4f3177bef9bb86ac3430db41994c8332f4afa31ff1c5178f",
    ),
    (
        "data/core/core-odpis-krs-high.json",
        "5bd0cbc74e75a2123e04211113b3cd6cbb0632ad7ce842344c57f61626e791f9",
    ),
    (
        "data/core/core-odpis-krs-low.json",
        "485fed8613b90d2e2beb736024476edf166efd7a1c3b38787cb8c9aa740dcee1",
    ),
    (
        "data/core/core-odpis-krs-medium.json",
        "dbd8f1ab5c3927b7eb70b49cc72887df30f5e147ac0692a651e6ba03aec22947",
    ),
    (
        "data/core/core-pismo-urzedowe-high.json",
        "6f70cba2cf90986d27079f9475ec37c86f10cc7753cb745a07f61def3dc3cfd0",
    ),
    (
        "data/core/core-pismo-urzedowe-low.json",
        "e9746dbe2b7540841f56ca430e78a9686fd2f664d6ec738c90ed7804746f9d1d",
    ),
    (
        "data/core/core-pismo-urzedowe-medium.json",
        "d3717aa806a1ac9e4e55be64310fe1da1063ec618416b8989e95b92a6e9bb8e3",
    ),
    (
        "data/core/core-protokol-zebrania-high.json",
        "9bf2cd8482875c30545cc21ed75373ac888d3cfc09a85731065083490c69bea0",
    ),
    (
        "data/core/core-protokol-zebrania-low.json",
        "68888493629477b0f4087d5065d41e7ae4cdb43938d4c7855c09afead8fc0cfb",
    ),
    (
        "data/core/core-protokol-zebrania-medium.json",
        "685ea3c4cb9050c9f2f3594d20d6dd7681b71fe168761fac2a212d6eb180d4d5",
    ),
    (
        "data/core/core-umowa-o-prace-high.json",
        "9ded647746536629de5aa4a162c75cf55de54eeee5dde3be4e1d26f85b8ed93a",
    ),
    (
        "data/core/core-umowa-o-prace-low.json",
        "b81db41f67b7bfac0703ff7122725854ece16402e63965409072e5cfe4d24ba5",
    ),
    (
        "data/core/core-umowa-o-prace-medium.json",
        "b19927dfc8e9a655cc11da16f45c196b7fa83850a14351150a381fb7417da6eb",
    ),
    (
        "data/core/core-umowa-zlecenie-high.json",
        "4e883a8e3addd5158e25f34c278060dde8544bdbd67d9b776099554d55981f7a",
    ),
    (
        "data/core/core-umowa-zlecenie-low.json",
        "f83d05e5710360e7e13e57087b9f00e12d782ae79e674916409094547222a618",
    ),
    (
        "data/core/core-umowa-zlecenie-medium.json",
        "8e58582bdd54c8eb52314dcc59fe167468027ec6475fbe23eb48c60717d90fee",
    ),
    (
        "data/core/core-wyciag-bankowy-high-alt1.json",
        "5b6b31ee7ad2c168f3f60fa45b601f60e50b3c1671a519938805ee265317d491",
    ),
    (
        "data/core/core-wyciag-bankowy-high.json",
        "851daba6bad67124865ea762c09a9bef8d19c5672cdab80e291175a3a6bad691",
    ),
    (
        "data/core/core-wyciag-bankowy-low.json",
        "4d2f3d8982abf557fb8c70b20a09d5e73e3778d1d07874acbf15370b6e5e6761",
    ),
    (
        "data/core/core-wyciag-bankowy-medium.json",
        "f92c304451f4a090acb216b5c72de5bb21318d21e42f89251225927ea918e76d",
    ),
    (
        "data/core/core-wyrok-001.json",
        "9928434b9541014f108342972c77e70dace2e705aec3a32bf7de574a13bc67b0",
    ),
    (
        "data/core/core-wyrok-high.json",
        "56a4ca46ebfa9bf85d20a87a0a0bb5497900e2d031121b4eea59c4c5459c207f",
    ),
    (
        "data/core/core-wyrok-low.json",
        "0bc5349843f3adc8e8e4217c6bb38d49f5dbcd2c25f6f530bfc6247a4a10217c",
    ),
    (
        "data/identifiers/identifiers-dowod.json",
        "983f93ebf72596b01f5e397100c89fabd67bee203db7305ac621cdeeb50fce74",
    ),
    (
        "data/identifiers/identifiers-driving-license.json",
        "7230d7c5167c8cfdad0e59e56feb755d3262c369654fc3bedca5f49d6b64b703",
    ),
    (
        "data/identifiers/identifiers-email.json",
        "41241d2d1f5ce2cc6f5d56cce15d4962ae5ca95796748a53b7eef1177f592c19",
    ),
    (
        "data/identifiers/identifiers-iban.json",
        "1fab68bbda0a1a9c2d28fdf571a719f3e10e2a6f375ee0f3c98ccc6d9806f1f2",
    ),
    (
        "data/identifiers/identifiers-nip.json",
        "a66dbecc176caa5d8eb2234911c73bffcb1fc164ead8f1f030ab02c8108a3b36",
    ),
    (
        "data/identifiers/identifiers-passport.json",
        "345b035f26a9fe1d8edede09d02a40a31a59aa15141dfcd06e64735eb114b639",
    ),
    (
        "data/identifiers/identifiers-payment-card.json",
        "521e6f89834d3d1fe8a31423f69087eeb190a9073ad9e1b87e61626966cca049",
    ),
    (
        "data/identifiers/identifiers-pesel.json",
        "55b34bbd5712a163c2c5c172f8b469d8e07c61a36a8bb1a85a0876e321a77dab",
    ),
    (
        "data/identifiers/identifiers-phone.json",
        "623abcce28d541b57211aa909e2c47454dc8ff7e29f1bdcc9a69760ccb15b618",
    ),
    (
        "data/identifiers/identifiers-regon.json",
        "463d32b4917975bc49953e4284ed3b3e9e0a14eab9eb12fd37e2a3d340fee92b",
    ),
    (
        "data/identifiers/identifiers-vehicle-plate.json",
        "de0beaff16b044f92d5d165d7487f7504c662e7983dec4357fa78f067c41e5f4",
    ),
    (
        "data/identifiers/identifiers-vin.json",
        "ec4f53de51dfe6b5feb8849839b9162cf9347992562bb6d6ad656a943bb89744",
    ),
    (
        "data/address/address-admin-unit.json",
        "85242425eea93d959ee44c5e2a1b54eac194032d202f5beaffaea119ae219278",
    ),
    (
        "data/address/address-al-prefix.json",
        "966e3adafe96dc4d8e3630030b54d50ff837876d7348fad329d7fa215e17b66e",
    ),
    (
        "data/address/address-bare-city.json",
        "8e93cc99614d0fffa627ac6c813e355568b8ceb3b87ba0b78b1a23d51ceb135e",
    ),
    (
        "data/address/address-building-letter.json",
        "acfae4e7c9a8ad114b04bbe5b4a05ba7021fa8a9bb18115658a5b6ebb6b72fef",
    ),
    (
        "data/address/address-flat-unit.json",
        "39aff0ba6cef0ee2883b3a5119b8e6ee560ca7f2ca75141166cc1932c26c4dd2",
    ),
    (
        "data/address/address-full.json",
        "bfc1d8926d8372c8b8be7667e34573787c8b6a866a2046e899dc94c9973414da",
    ),
    (
        "data/address/address-inflected.json",
        "afd7a088c4924c8212cf7e789f0dda77ce0e5f53ff36608a7621d255f31719b0",
    ),
    (
        "data/address/address-letterhead-block.json",
        "14087a8528e947e59671e742597473232935393a511a7827e37bb9eaffb99260",
    ),
    (
        "data/address/address-loc-in-org.json",
        "28e3ff07f30f5e1a9429a294cf7de1347d65a17db8f1575654c1e1a8ba26c3be",
    ),
    (
        "data/address/address-osiedle-block.json",
        "7bbdc2ca1bc38486982b541f52239e8bfe92fcca0402fa6caa98732c13ed9ec1",
    ),
    (
        "data/address/address-person-named-streets.json",
        "df667d0e965739eaeccb4cae10329b1b54f1fac572af4f49fdd2199fa9248798",
    ),
    (
        "data/address/address-pl-prefix.json",
        "f0a7b3bd8bb2652133d2b01f837d9a09e38b1b9e0b184841d300274f36d5e674",
    ),
    (
        "data/address/address-po-box.json",
        "92b7cab370ec8186d16165f85301dbda4cab930fd4b0f10677537f9400fb0248",
    ),
    (
        "data/address/address-street-only.json",
        "522b4ce398e537946849d682903b374f87c9a7bf719e767d3b006f5bb9fbfbc6",
    ),
    (
        "data/negative/lookalike-001.json",
        "7152ad26f5df8dbb598a550176d8e80d394c9b6222782c1b7e99075d84786839",
    ),
    (
        "data/negative/lookalike-002-ledger.json",
        "f43135718e4bdf69a633b24343953e594d3617c7475c72c7bfd9fbedae0883eb",
    ),
    (
        "data/negative/lookalike-003-legal.json",
        "9d90413de3c2d6f61f23be67cd6f0d0b1e3a6901db927df638d7f1fe5f40e489",
    ),
    (
        "data/negative/negative-date-serial-lookalike.json",
        "4cd64890f82144dcb76df66cdbeae9e606dbc798ad9b9debd09eebf558fcb67b",
    ),
    (
        "data/negative/negative-domain-address-collision.json",
        "b140e964e28fd5c3974c0b58a7d82bcdf0927a39606decd994f707ee18de7c19",
    ),
    (
        "data/negative/negative-institutional-fund-terms.json",
        "9be96cf39193796b2e26078375d941d963d8c43e32efbce9e43d69b4cf9ba7b9",
    ),
    (
        "data/negative/negative-invoice-order-numbers.json",
        "9017a0d8c95a50ffd3b15e744d18d4d87456146000a88eb4f4582336cdc6bc50",
    ),
    (
        "data/negative/negative-legal-form-enumeration.json",
        "5d501d005827aad71311de07a6436f53b31097ed91567bca52620036cf8be280",
    ),
    (
        "data/negative/negative-network-product-codes.json",
        "659a128c27ab66db18185cb80897f9e9f71cf470a48e222f37de1f628df7ed17",
    ),
    (
        "data/negative/negative-part-serials.json",
        "144978792504644f6b8187519795aa70c02a2201da551d5c4a90c7272b7933ca",
    ),
    (
        "data/negative/negative-plate-context-lookalike.json",
        "3c20bc27e2ff5bdaa35caf6e0e135b2bd2086f83019f7b2c57a051f77b1a4771",
    ),
    (
        "data/negative/negative-standards-room-codes.json",
        "1fa673802235e38432dc5ac1af689079da022c0be087bf1155d897cb423ba9b6",
    ),
    (
        "data/negative/negative-titles-programmes-forms.json",
        "662c52c4deae762d9753844cb5bc516f0d2600ddf87e9ab99e456d9e18ee1558",
    ),
    (
        "data/negative/negative-urls-handles-paths.json",
        "4267d7a7025dbe227933a74edbe5b8df38a6d80dbad3fb20aeed5d5a37fe6029",
    ),
    (
        "data/inflection/inflection.jsonl",
        "5b15af089d7143a45cef59a51dbf974a94793cfa7fd1dab399b7ac477d830dbe",
    ),
)

#: Downloads are cached by file name: each name's lane (the directory under ``data/``).
_LANES = {Path(path).name: Path(path).parent.name for path, _ in FILES}
assert len(_LANES) == len(FILES)  # noqa: S101 (file names are unique across the lanes)

_E = EntityType
LABELS = LabelMap(
    types={
        "PERSON": _E.PERSON,
        "ORG": _E.ORGANIZATION,
        "PESEL": _E.ID_DOCUMENT,
        "DOWOD": _E.ID_DOCUMENT,
        "PASSPORT": _E.ID_DOCUMENT,
        "DRIVING_LICENSE": _E.ID_DOCUMENT,
        "NIP": _E.ID_DOCUMENT,
        "IBAN": _E.BANK_ACCOUNT,
        "PAYMENT_CARD": _E.BANK_ACCOUNT,
        "EMAIL": _E.EMAIL,
        "PHONE": _E.PHONE,
        "DOB": _E.DATE_OF_BIRTH,
        "VEHICLE_PLATE": _E.VEHICLE_PLATE,
        "LOC": _E.ADDRESS,
        "LOC_PLACE": _E.ADDRESS,
        "POSTAL": _E.ADDRESS,
        "REGON": None,
        "VIN": None,
    },
    part_only=frozenset({"LOC_PLACE", "POSTAL"}),
    notes={
        "ORG": "ORGANIZATION is a keep type: scored for recall, never a leak",
        "PESEL": "national identifiers and identity documents are ID_DOCUMENT",
        "NIP": "a tax number; a sole trader's NIP identifies a person",
        "LOC": "a LOC with a digit (a street address)",
        "LOC_PLACE": "a LOC without a digit (a town, an admin unit): ADDRESS inside an address",
        "POSTAL": "ADDRESS inside an address; a postcode on its own is policy-excluded",
        "REGON": "a business register number identifies a business",
        "VIN": "a vehicle identification number: pii-guard has no type for it",
    },
)


def _label(entity: dict[str, Any], value: str) -> str:
    label = str(entity["label"])
    if label == "LOC" and not any(c.isdigit() for c in value):
        return "LOC_PLACE"
    return label


def rows(paths: Sequence[Path]) -> Iterator[Row]:
    for path in paths:
        if path.suffix == ".jsonl":  # the inflection lane: one entity per row
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    uid = f"inflection-{raw['entity_id']}-{raw['case']}".replace(":", "-")
                    text = str(raw["text"])
                    start, end = int(raw["start"]), int(raw["end"])
                    yield Row(
                        uid,
                        "pl",
                        text,
                        ((start, end, _label(raw, text[start:end])),),
                        meta={
                            "lane": "inflection",
                            "case": raw["case"],
                            "category": raw["category"],
                        },
                    )
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        axes = raw.get("axes") or {}
        meta = {"lane": raw.get("lane") or _LANES[path.name], "doc_type": axes.get("doc_type")}
        entities = raw.get("entities") or []
        yield Row(
            str(raw["doc_id"]),
            "pl",
            str(raw["text"]),
            tuple((int(e["start"]), int(e["end"]), _label(e, str(e["text"]))) for e in entities),
            meta=meta,
            values=tuple(str(e["text"]) for e in entities),
        )


DATASET = Dataset(
    name="pl-pii-bench",
    title="pl-pii-bench v1.0.0",
    homepage=f"https://huggingface.co/datasets/{REPO}",
    revision=REVISION,
    files=tuple(
        SourceFile(path, f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{path}", sha)
        for path, sha in FILES
    ),
    license="CC-BY-4.0",
    license_url="https://creativecommons.org/licenses/by/4.0/",
    attribution="pl-pii-bench, version 1.0.0, Anonimator, CC BY 4.0",
    languages=("pl",),
    source_split="core, identifiers, address, negative and inflection lanes (all documents)",
    split="test",
    synthetic=True,
    commit_rows=True,
    description="synthetic Polish documents, checksum-valid ids, invalid lookalikes, 7 cases",
    sample={"pl": 346},
    seed=2026,
    labels=LABELS,
    read=rows,
    notes=(
        "Synthetic, generated with exhaustive annotation; every identifier is fictional.",
        "Its card asks that it never be trained on: training/ner/decontam.py drops near-"
        "duplicates of it from any training file.",
        "pii-guard has no Polish language pack: rules run their language-neutral patterns "
        "only, so this set measures how far the NER carries an unseen language.",
        "The maintainer also maintains one of the systems it measures (its card says so).",
    ),
)
