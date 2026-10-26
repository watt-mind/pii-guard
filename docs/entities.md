# Entity taxonomy

> Status: proposed. The first language is Hungarian (`hu`); identifiers below marked `hu` are
> country-specific, the rest are language-independent or apply across the EU.

Each entity type has a default **policy**: `mask` (replace with a pseudonym), `keep` (leave as
is) or `block` (refuse the request). Deployments can override policies.

## Text entities

| Type | Examples | Detected by | Default |
|---|---|---|---|
| `PERSON` | Names, including inflected forms | NER, LLM | mask |
| `ADDRESS` | Street addresses, written in any order or in prose | LLM, NER, postcode rules | mask |
| `EMAIL` | Email addresses | rules | mask |
| `PHONE` | Phone numbers, national and international formats | rules | mask |
| `DATE_OF_BIRTH` | Dates in a birth-date context | LLM (context), rules (format) | mask |
| `NATIONAL_ID_HU_TAX` | Hungarian personal tax ID (adóazonosító jel), 10 digits with checksum | rules | mask |
| `NATIONAL_ID_HU_TAJ` | Hungarian social security (TAJ) number, 9 digits with checksum | rules | mask |
| `ID_DOCUMENT` | ID card, passport and driving licence numbers | rules, LLM (context) | mask |
| `BANK_ACCOUNT` | IBAN (with checksum) and Hungarian giro account numbers | rules | mask |
| `COMPANY_ID_HU` | Company registration number (cégjegyzékszám), company tax number | rules | keep |
| `ORGANIZATION` | Company and institution names | NER, LLM | keep |
| `PARCEL_NUMBER_HU` | Land registry parcel number (helyrajzi szám) | rules, LLM (context) | mask |
| `VEHICLE_PLATE` | Licence plates | rules | mask |

`ORGANIZATION` and company identifiers default to `keep` because they're usually not personal
data and the model needs them to reason. A sole trader's company name can contain a person's
name, though; the LLM pass is expected to flag that case as `PERSON`.

## Visual entities

| Type | Examples | Detected by | Default |
|---|---|---|---|
| `FACE` | Faces in photos and on ID documents | SAM 3.1 | mask |
| `SIGNATURE` | Handwritten signatures | SAM 3.1 | mask |
| `ID_PHOTO` | The photo area of an ID document | SAM 3.1 | mask |
| `STAMP` | Official stamps and seals | SAM 3.1 | keep |
| *(text types above)* | Text found in an image by OCR | OCR + `detect` | per type |

## Adding a language

A language needs: its rules (national identifiers, phone and postcode formats), a morphology
module for matching and re-applying inflected forms, and a synthetic corpus for evaluation.
The NER and LLM passes are multilingual and are re-measured, not rewritten.
