# Entity taxonomy

> Status: proposed. Built-in languages: Hungarian (`hu`) and English (`en`). The entity types
> below are shared by every language; the per-language tables say which identifiers each
> language pack's rules find and which type they map to ([ADR 0008](decisions/0008-language-packs.md)).

Each entity type has a default **policy**: `mask` (replace with a pseudonym), `keep` (leave as
is) or `block` (refuse the request). Deployments override policies with
`PII_GUARD_POLICY_OVERRIDES`, e.g. `ORGANIZATION=mask,EMAIL=block` (validated at startup).
The defaults in the `Default` columns below are `pii_guard.policy.DEFAULT_POLICIES`; a test
keeps the two in sync. See [contracts.md](contracts.md#entity-policies-implemented).

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
| `ID_DOCUMENT` | ID card, passport, driving licence and residence permit numbers; machine-readable zones (MRZ) of ID documents; national numbers without their own type (Hungarian személyi azonosító, US SSN, UK NINO) | rules, LLM (context) | mask |
| `BANK_ACCOUNT` | IBAN (with checksum), Hungarian giro account numbers, payment card numbers (Luhn) | rules | mask |
| `COMPANY_ID_HU` | Company registration number (cégjegyzékszám), company tax number | rules | keep |
| `ORGANIZATION` | Company and institution names | NER, LLM | keep |
| `PARCEL_NUMBER_HU` | Land registry parcel number (helyrajzi szám) | rules, LLM (context) | mask |
| `VEHICLE_PLATE` | Licence plates | rules | mask |

`ORGANIZATION` and company identifiers default to `keep` because they're usually not personal
data and the model needs them to reason. A sole trader's company name can contain a person's
name, though; the LLM pass is expected to flag that case as `PERSON`.

## Per language

Rules run in one of three scopes: **all** (language-independent, every text), **everywhere**
(a language pack's validated identifiers, run whatever the text's language) and **language**
(only when the request's `language` is that pack's). Names, organisations, prose addresses and
dates of birth come from the NER and LLM passes in every language.

### Language-independent

| Identifier | Type | Validation | Scope |
|---|---|---|---|
| IBAN, compact or grouped | `BANK_ACCOUNT` | country length + mod 97 | all |
| Email address | `EMAIL` | shape | all |
| International phone number (`+<country>`, not `+36`) | `PHONE` | 8–15 digits (E.164) | all |
| Payment card number, compact or in groups of 4 (Amex 4-6-5) | `BANK_ACCOUNT` | issuer prefix + length + Luhn | all |

Payment cards use `BANK_ACCOUNT` until the taxonomy has a card type of its own.

### Hungarian (`hu`)

| Identifier | Type | Validation | Scope |
|---|---|---|---|
| Personal tax ID (adóazonosító jel) | `NATIONAL_ID_HU_TAX` | mod 11 | everywhere |
| Social security (TAJ) number | `NATIONAL_ID_HU_TAJ` | weighted mod 10 | everywhere |
| Giro account number (16 or 24 digits) | `BANK_ACCOUNT` | weights 9-7-3-1 per block | everywhere |
| Phone number (`+36`, `0036`, `06`) | `PHONE` | area code and length | everywhere |
| Company registration number (cégjegyzékszám) | `COMPANY_ID_HU` | court and form codes | everywhere |
| Company tax number (adószám) | `COMPANY_ID_HU` | check digit, VAT and area code | everywhere |
| Postcode before a settlement name or in context | `ADDRESS` | 4 digits, not an amount | language |
| Vehicle plate (`ABC-123`, `AA BC-123`) | `VEHICLE_PLATE` | format | language |
| Personal identification number (személyi azonosító, `1-710304-1237`) | `ID_DOCUMENT` | sex/century digit, date of birth, mod 11 (weights reversed from 1997) | everywhere |
| ID card (`123456AB`), passport (`AB1234567`), driving licence (`AB123456`) number next to its label, before (`személyi igazolvány száma:`) or after (`… számú személyi igazolvány`) | `ID_DOCUMENT` | format + label, also unaccented (`szemelyi`, `szigszam`) | everywhere |
| Other document number (residence permit, foreign ID) after its label | `ID_DOCUMENT` | 6–12 letters and digits, at least one of each + label (scores lower) | everywhere |
| ID card number `123456AB` without a label | `ID_DOCUMENT` | format only (scores lowest) | language |
| Machine-readable zone, TD1 (ID card, 3 × 30) and TD3 (passport, 2 × 44) | `ID_DOCUMENT` | ICAO 9303 check digits (a zone whose digits fail, e.g. after OCR, scores lower) | everywhere |
| Land registry parcel number (`1234/5`, `0123/4`, `0123/4/A/12`) next to `hrsz.` / `helyrajzi szám`, also listed (`hrsz.: 1/2, 1/3 és 1/4`) | `PARCEL_NUMBER_HU` | format + label; settlement or `belterület`/`külterület` nearby raises the score | everywhere |

A whole MRZ is one span: it holds the holder's name, document number and date of birth.
Parcel numbers always need their label, so fractions (`1/2 arányú`), dates (`2026/10.`), page
numbers (`3/5. oldal`) and court case numbers (`12.P.21.345/2025/7.`) stay unmasked.

Vault inflection: case suffixes kept outside the placeholder (`[[PERSON_7f3a]]nek`), also
when the stem changes: final-vowel lengthening (`Próba Zsuzsannának` → `[[PERSON_7f3a]]nak`)
and consonant or digraph doubling (`Teszt Elekkel` → `[[PERSON_7f3a]]kel`, `Kováccsal` →
`[[PERSON_9b2c]]al`). All forms of a name share one placeholder; unmask re-inflects it.

### English (`en`)

| Identifier | Type | Validation | Scope |
|---|---|---|---|
| US Social Security number `123-45-6789` | `ID_DOCUMENT` | no `000`/`666`/`9xx` area, `00` group, `0000` serial | everywhere |
| US SSN with spaces or none, after an "SSN" / "social security" label | `ID_DOCUMENT` | as above + label | language |
| UK National Insurance number `AB 12 34 56 C` | `ID_DOCUMENT` | prefix letter rules, suffix A–D | everywhere |
| UK national phone number (`020 7946 0000`, `07700 900123`) | `PHONE` | trunk `0`, 10–11 digits | language |
| US/NANP phone number (`(202) 555-0143`, `1-202-555-0143`) | `PHONE` | area and exchange `[2-9]XX`, not N11 | language |
| UK postcode (`SW1A 1AA`) | `ADDRESS` | outward/inward letter rules | language |
| US ZIP code after a state abbreviation or a "ZIP" label | `ADDRESS` | 5 or 5+4 digits + context | language |
| UK vehicle registration (`AB12 CDE`) | `VEHICLE_PLATE` | age identifier, no I/Q | language |
| Passport or driving licence number after its label | `ID_DOCUMENT` | 6–18 letters/digits, one digit + label | language |

Vault inflection: possessives kept outside the placeholder (`Smith's` → `[[PERSON_7f3a]]'s`,
`James'`); plurals are not matched.

## Visual entities

| Type | Examples | Detected by | Default |
|---|---|---|---|
| `FACE` | Faces in photos and on ID documents | SAM 3.1 | mask |
| `SIGNATURE` | Handwritten signatures | SAM 3.1 | mask |
| `ID_PHOTO` | The photo area of an ID document | SAM 3.1 | mask |
| `STAMP` | Official stamps and seals | SAM 3.1 | keep |
| *(text types above)* | Text found in an image by OCR | OCR + `detect` | per type |

## Adding a language

See [ADR 0008](decisions/0008-language-packs.md). A language pack contributes rules
(`detect/rules/<code>.py`), a vault inflection matcher if the language inflects names, LLM
prompt notes, eval surface forms if it has stem changes, a synthetic fixture set, and a table
in this file. Every piece is optional and falls back to language-independent behaviour; the
NER and LLM passes are multilingual and are re-measured, not rewritten.
