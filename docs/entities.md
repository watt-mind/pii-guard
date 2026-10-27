# Entity taxonomy

> Status: proposed. Built-in languages: Hungarian (`hu`), English (`en`) and German (`de`). The entity types
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
data and the model needs them to reason. A company name can contain a person's name, though:
a sole trader's (`Horváth Emese e.v.`) always does, and small partnerships and companies are
often named after their members (`Tóth és Társa Bt.`, `Kiss-Lukács Kft.`). For Hungarian a
rule finds that name part in every mode, fast mode included, and emits it as `PERSON`; the
resolver lets a `PERSON` win over the overlapping kept `ORGANIZATION`, so only the name is
masked (`[[PERSON_x]] és Társa Bt.`) and the rest of the company name stays. See "Person names
in company names" below.

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

| Person name inside a company name with a legal form (`e.v.`, `ev.`, `egyéni vállalkozó`, `Bt.`, `Kkt.`, `Kft.`, `Zrt.`, `Nyrt.`, `Kht.`, `Nonprofit Kft.`; any case, with or without the full stop, inflected: `Bt.-nek`) | `PERSON` | surname / given-name lexicons + legal form; see below | language |

A whole MRZ is one span: it holds the holder's name, document number and date of birth.
Parcel numbers always need their label, so fractions (`1/2 arányú`), dates (`2026/10.`), page
numbers (`3/5. oldal`) and court case numbers (`12.P.21.345/2025/7.`) stay unmasked.

#### Person names in company names

`pii_guard.languages.hu.companies` looks at the capitalised words right before a legal form
and masks the person's name only:

| Company name | Masked | Why |
|---|---|---|
| `Horváth Emese e.v.`, `Balogh Ernő egyéni vállalkozónak` | the name (0.9) | sole trader: the business name is the person |
| `Ördögh Tihamér e.v.` | the name (0.7) | sole trader, surname not in the lexicon: the legal form is enough |
| `Molnár Péter Bt.`, `Fekete Anna Kft.` | the name (0.9) | surname + given name, any form |
| `Tóth és Társa Bt.`, `Szabó és Fiai Kkt.`, `Varga és Kiss Kkt.` | the surname(s) (0.85) | family or partner connector |
| `Horváth Bt.`, `Kiss-Lukács Kft.`, `Mészáros Építő Kft.` | the surname (0.8 / 0.75) | a surname that is not an ordinary word |
| `Kis Bt.` | the surname (0.7) | a partnership's name traditionally carries a member's name |
| `Fekete Kft.`, `Magyar Kalapács Zrt.`, `Pécsi Kerámia Kft.`, `Vörös Rózsa Kft.` | nothing | an ordinary word (adjective, occupation, demonym, place adjective; a flower) with no person evidence |
| `Pannon Csempe Kft.`, `Duna Lámpa Bt.` | nothing | no surname |

**The false-positive decision.** Many Hungarian surnames are also everyday words (`Nagy`,
`Kis`, `Fekete`, `Magyar`, `Szabó`, `Molnár`, `Kovács`, `Varga`; demonyms such as `Lengyel`;
place adjectives such as `Pécsi`), and businesses use them as brand words. Such a surname on
its own is masked only with person evidence: a given name next to it (unless that given name is
itself a common word, as in `Vörös Rózsa`), a family connector, a sole-trader form, or a bare
surname in a `Bt.`/`Kkt.`. So `Fekete Kft.` and `Kovács Autószerviz Kft.` stay unmasked even
when they are in fact named after a person; the NER and LLM passes may still catch them, and
lower-case names (`kovács bt.`) are left to them.

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

### German (`de`)

German IBANs and `+49` phone numbers are found by the language-independent rules.

| Identifier | Type | Validation | Scope |
|---|---|---|---|
| Sozialversicherungsnummer (`12 150885 M 01 2`, compact or spaced) | `ID_DOCUMENT` | area 02–89, date `DDMMYY`, letter, weighted check digit | everywhere |
| Steuer-ID (`12 345 678 901`) next to `Steuer-ID` / `Steueridentifikationsnummer` / `IdNr` | `ID_DOCUMENT` | ISO 7064 MOD 11,10 + one repeated digit + label | everywhere |
| Steuer-ID without a label | `ID_DOCUMENT` | as above (scores lower) | language |
| National phone number (`030 12345678`, `(0221) 4567890`, `0171/2345678`) | `PHONE` | trunk `0`, 9–12 digits, not an amount | language |
| Street address (`Musterstraße 12[, 10115 Berlin]`, `Am Beispielweg 3a`) | `ADDRESS` | street-type word + house number | language |
| Postcode and place at the start of an address line (`50667 Köln`) | `ADDRESS` | 5 digits, line start or after a comma, not an amount | language |

Vault inflection: the genitive kept outside the placeholder (`Annas` → `[[PERSON_7f3a]]s`,
`Hans'`, colloquial `Anna's`).

## Visual entities

| Type | Examples | Detected by | Default |
|---|---|---|---|
| `FACE` | Faces in photos and on ID documents | SAM 3.1 | mask |
| `SIGNATURE` | Handwritten signatures | SAM 3.1 | mask |
| `ID_PHOTO` | The photo area of an ID document | SAM 3.1 | mask |
| `STAMP` | Official stamps and seals | SAM 3.1 | keep |
| *(text types above)* | Text found in an image by OCR | OCR + `detect` | per type |

## Adding a language

See [languages.md](languages.md) and [ADR 0010](decisions/0010-language-pack-plugins.md).
A language pack (`src/pii_guard/languages/<code>/`) contributes rules, a vault inflection
matcher if the language inflects names, LLM prompt notes, eval surface forms if it has stem
changes, a smoke fixture set, and a table in this file. Every piece is optional and falls back to language-independent behaviour; the
NER and LLM passes are multilingual and are re-measured, not rewritten.
