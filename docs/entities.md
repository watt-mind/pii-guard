# Entity taxonomy

> Status: proposed. Built-in languages: Hungarian (`hu`), English (`en`), German (`de`) and Polish (`pl`). The entity types
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
| `EMAIL` | Email addresses | rules, NER (v2) | mask |
| `PHONE` | Phone numbers, national and international formats | rules, NER (v2) | mask |
| `DATE_OF_BIRTH` | Dates in a birth-date context | LLM (context), rules (format) | mask |
| `NATIONAL_ID_HU_TAX` | Hungarian personal tax ID (adóazonosító jel), 10 digits with checksum | rules, NER (v2) | mask |
| `NATIONAL_ID_HU_TAJ` | Hungarian social security (TAJ) number, 9 digits with checksum | rules, NER (v2) | mask |
| `ID_DOCUMENT` | ID card, passport, driving licence and residence permit numbers; machine-readable zones (MRZ) of ID documents; national numbers without their own type (Hungarian személyi azonosító, US SSN, UK NINO) | rules, NER (v2), LLM (context) | mask |
| `BANK_ACCOUNT` | IBAN (with checksum), Hungarian giro account numbers, payment card numbers (Luhn) | rules, NER (v2) | mask |
| `COMPANY_ID_HU` | Company registration number (cégjegyzékszám), company tax number | rules | keep |
| `ORGANIZATION` | Company and institution names | NER, LLM | keep |
| `PARCEL_NUMBER_HU` | Land registry parcel number (helyrajzi szám) | rules, LLM (context) | mask |
| `VEHICLE_PLATE` | Licence plates | rules | mask |
| `SECRET` | API keys and tokens (AWS, GitHub, Slack, Stripe, `sk-` style, Google, JWT), PEM private keys, passwords in URLs, values assigned to a secret-ish key (`API_KEY=`, `password:`, `Authorization: Bearer`) | rules (language-independent) | mask |

`ORGANIZATION` and company identifiers default to `keep` because they're usually not personal
data and the model needs them to reason. A company name can contain a person's name, though:
a sole trader's (`Horváth Emese e.v.`) always does, and small partnerships and companies are
often named after their members (`Tóth és Társa Bt.`, `Kiss-Lukács Kft.`). For Hungarian a
rule finds that name part in every mode, fast mode included, and emits it as `PERSON`; the
resolver lets a `PERSON` win over the overlapping kept `ORGANIZATION`, so only the name is
masked (`[[PERSON_x]] és Társa Bt.`) and the rest of the company name stays. See "Person names
in company names" below.

The other way round, the NER model sometimes calls a bare company or product name a person
(`Write a haiku about Meta`). An NER `PERSON` span that is exactly a listed brand name (the
language packs' `brands.tsv`, [detect/ner_orgs.py](../src/pii_guard/detect/ner_orgs.py),
LAB-1336) becomes `ORGANIZATION` and is kept, unless it is part of a longer name or follows an
honorific (`Meta Kovács`, `Ms. Apple`). `PII_GUARD_NER_BRANDS=false` turns this off.

### NER label set

The NER detector (`pii_guard.detect.ner`) reports a subset of the types above. A v1 checkpoint
(LAB-1106, LAB-1128) knows four; a v2 checkpoint (LAB-1150) also proposes identifiers, so a
number whose checksum fails or whose format no rule knows is still masked. Labels are the
pii-guard type names (`B-PHONE`, `I-NATIONAL_ID_HU_TAX`, …), so they map one to one. GLiNER
(`pii_guard.detect.ner_gliner`) is asked for natural-language label names, mapped the same way.

| NER label (v2) | pii-guard type | Trained from | GLiNER label name |
|---|---|---|---|
| `PERSON` | `PERSON` | corpus gold + Glimmer, OpenPII `GIVENNAME`+`SURNAME` | person |
| `ADDRESS` | `ADDRESS` | corpus gold, OpenPII `STREET`, `BUILDINGNUM`, `ZIPCODE`, `CITY` in an address | street address |
| `ORGANIZATION` | `ORGANIZATION` | corpus gold + Glimmer | organization |
| `DATE_OF_BIRTH` | `DATE_OF_BIRTH` | corpus gold (OpenPII `DATE` is left out of the loss) | date of birth |
| `EMAIL` | `EMAIL` | corpus gold, OpenPII `EMAIL` | email address |
| `PHONE` | `PHONE` | corpus gold, OpenPII `TELEPHONENUM` | phone number |
| `ID_DOCUMENT` | `ID_DOCUMENT` | corpus gold, OpenPII `IDCARDNUM`, `PASSPORTNUM`, `DRIVERLICENSENUM`, and `SOCIALNUM` / `TAXNUM` outside Hungarian | identity document number |
| `NATIONAL_ID_HU_TAX` | `NATIONAL_ID_HU_TAX` | corpus gold, OpenPII `TAXNUM` in Hungarian rows | hungarian tax identification number |
| `NATIONAL_ID_HU_TAJ` | `NATIONAL_ID_HU_TAJ` | corpus gold, OpenPII `SOCIALNUM` in Hungarian rows | hungarian social security number |
| `BANK_ACCOUNT` | `BANK_ACCOUNT` | corpus gold (IBAN, giro), OpenPII `CREDITCARDNUMBER` | bank account or card number |

How the spans are used: the NER **proposes**; the rules keep their validated spans and
scores. In the resolver (`detect/pipeline.py`) a rule span of a structured type keeps its
exact boundaries and absorbs an overlapping NER span of the same type, and wins a type
conflict, so a validated IBAN is never cut short by a NER guess. Policy then decides as for
any other span. Corpus gold of a type the NER isn't trained on (plates, parcel and company
numbers) is left out of the loss, never taught as "not personal data". Titles, ages, gender
and a town on its own stay `O`, as the policy keeps them.

Not in the label set: **usernames, IP addresses and URLs with an identity in them.** pii-guard
has no entity type for them yet (adding one is a taxonomy and policy change, not a model
change), and neither training source labels them. Tracked as a follow-up.

## Per language

Rules run in one of three scopes: **all** (language-independent, every text), **everywhere**
(a language pack's validated identifiers, run whatever the text's language) and **language**
(only when the request's `language` is that pack's). Names, organisations, prose addresses and
dates of birth come from the NER and LLM passes in every language.

### Language-independent

| Identifier | Type | Validation | Scope |
|---|---|---|---|
| IBAN, compact or grouped | `BANK_ACCOUNT` | country length (SWIFT registry) + mod 97 | all |
| Email address, also with a punycode TLD (`xn--p1ai`) or a quoted local part | `EMAIL` | shape | all |
| International phone number (`+<country>`, not `+36`) | `PHONE` | 8–15 digits (E.164) | all |
| Payment card number, compact or in groups of 4 (Amex 4-6-5) | `BANK_ACCOUNT` | issuer prefix + length + Luhn | all |
| Provider key shapes: AWS access key id, GitHub (`ghp_`, `github_pat_`), Slack (`xox?-`), Stripe (`sk_`/`rk_` `live`/`test`, `whsec_`), `sk-` style (OpenAI, Anthropic), Google (`AIza`), JWT, PEM private-key block | `SECRET` | prefix + length (+ letters and digits for `sk-`) | all |
| Password (and a non-generic user name) in `scheme://user:password@host` | `SECRET` | not a reference (`${DB_PASSWORD}`, `<password>`) | all |
| Value assigned to a secret-ish key (`*_KEY`, `*_TOKEN`, `*_SECRET`, `PASSWORD`, `PASSWD`, `*_PWD`, `AUTH`, `BEARER`; `.env`, YAML, JSON, shell, CLI flags) and `Authorization: Bearer/Basic <token>` | `SECRET` | a literal, not code: 4+ characters, not a reference, call, type name, boolean, number (except for passwords) or mask (`****`) | all |

Payment cards use `BANK_ACCOUNT` until the taxonomy has a card type of its own.

`SECRET` spans carry a subtype (`Span.subtype`: `github_token`, `url_password`, `assignment`
...; [contracts.md](contracts.md)). A hash, UUID or git SHA is a secret only when it is assigned
to a secret-ish key (`WEBHOOK_SECRET=<sha256>`); lockfile integrity hashes and commit ids are
left alone. A generic `*_KEY` name (`STRIPE_KEY`, but also `STORAGE_KEY`) needs a value that
looks generated (16+ characters, letters and digits), so lookup names stay readable.

**Cued numbers** (all scopes, `PII_GUARD_RULES_CUED_NUMBERS`, default on). A digit or
alphanumeric run right after a strong cue word from a pack's `cues.tsv` (`TAJ`,
`adóazonosító`, `kártyaszám`, `passport`, `Steuer-ID`, `IBAN`, `telefon` ...) is masked as the
cued type even when its checksum fails or its phone numbering plan is unknown, at score 0.6
(validated hits score 0.7–0.99 and win any overlap). The value must have the type's shape
(phone 7–15 digits, card or account 12–34 characters, tax ID 10–11 digits, TAJ 9 digits,
document numbers 6–20 letters and digits with at least two digits); dates, amounts and
numbers after an order, invoice or reference cue are never masked
([languages.md](languages.md#3-rules)). Measured in [journey.md](journey.md) (milestone 28).

### Hungarian (`hu`)

| Identifier | Type | Validation | Scope |
|---|---|---|---|
| Personal tax ID (adóazonosító jel) | `NATIONAL_ID_HU_TAX` | mod 11 | everywhere |
| Social security (TAJ) number next to its `TAJ` cue | `NATIONAL_ID_HU_TAJ` | weighted mod 10 + label | everywhere |
| TAJ number without its cue, not right after an order, invoice or reference label, an ID prefix (`INV-`, `#`) or a currency (one nine-digit run in ten passes the check) | `NATIONAL_ID_HU_TAJ` | weighted mod 10 | language |
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

### Polish (`pl`)

Polish IBANs and `+48` phone numbers are found by the language-independent rules. A REGON is a
business number, but a sole trader's identifies a person, as a NIP does.

| Identifier | Type | Validation | Scope |
|---|---|---|---|
| PESEL (`85031401234`) next to `PESEL` | `ID_DOCUMENT` | weights 1-3-7-9, a possible date of birth (month offset by century) + label | everywhere |
| NIP (`123-456-32-18`, `123-45-63-218`, compact) next to `NIP` | `ID_DOCUMENT` | weights 6-5-7-2-3-4-5-6-7 mod 11 + label | everywhere |
| EU VAT number `PL` + NIP (`PL1234563218`) | `ID_DOCUMENT` | NIP check digit | everywhere |
| REGON, 9 or 14 digits, next to `REGON` | `ID_DOCUMENT` | mod 11 check digit(s) + label | everywhere |
| ID card, dowód osobisty (`ABA 300000`) next to `dowód`, `seria i numer`, `nr dokumentu` | `ID_DOCUMENT` | 3 letters + 6 digits, weights 7-3-1-9-7-3-1-7-3 + label | everywhere |
| Passport (`AA 0000000`) next to `paszport` / `passport` | `ID_DOCUMENT` | 2 letters + 7 digits, weights 7-3-9-1-7-3-1-7-3 + label | everywhere |
| PESEL, NIP, ID card, passport without a label | `ID_DOCUMENT` | as above, not after an order, invoice or amount label (scores lower) | language |
| National phone number (`555 123 456`, `(22) 555 12 34`) | `PHONE` | mobile 3-3-3 starting 4–8, landline 2-3-2-2, not an amount | language |
| Street address (`ul. Kwiatowa 12/5[, 00-950 Warszawa]`, `al.`, `os.`, `pl.`) | `ADDRESS` | street-type word + name + house number | language |
| Postcode and place (`31-008 Kraków`) | `ADDRESS` | `NN-NNN` + capitalised place | language |
| Driving-licence number (`00123/16/1234`, `05936/42/00`) after `prawo jazdy`; any number above with a bad check digit after its cue | `ID_DOCUMENT` | cue + shape (`cues.tsv`) | everywhere |

Vault inflection: case endings that leave the written name intact are kept outside the
placeholder (`Nowaka` → `[[PERSON_7f3a]]a`, `Kowalskiego` → `[[PERSON_7f3a]]ego`); forms
whose stem changes (`Annie`, `Kowalskiej`) are matched as written.

## Visual entities

| Type | Examples | Detected by | Default |
|---|---|---|---|
| `FACE` | Faces in photos and on ID documents | SAM 3.1 | mask |
| `SIGNATURE` | Handwritten signatures | SAM 3.1 | mask |
| `ID_PHOTO` | The photo area of an ID document | SAM 3.1 | mask |
| `STAMP` | Official stamps and seals | SAM 3.1 | keep |
| *(text types above)* | Text found in an image by OCR | OCR + `detect` | per type |
| *(text types above)* | The value printed next to a known field caption (`Név`, `Date of birth`, EU licence field `1.`) | OCR + caption lexicon (`visual/captions.py`) | per type |

On ID cards a value sits under or beside a small caption (`Családi név / Surname` above
`FIKTÍV`), and a text detector reading the value alone often misses it: a surname on its own
line, a foreign date format, a document number with no checksum. Image masking therefore also
pairs every recognised caption with its value and masks the value with the caption's type.
The captions come from the language packs (`captions.tsv`, [languages.md](languages.md)),
plus French, Italian, Spanish, Polish and Dutch captions until those languages have packs,
and the EU driving licence field numbers (`1.` surname, `2.` given names, `3.` date and
place of birth, `5.` licence number, `8.` address) on a page where at least three of them
start a line. Captions of values that are not personal data (`Sex`, `Nationality`, `Expiry`)
are recognised too, so they bound the columns, but their values stay visible. A word is
masked only as the value of a personal-data caption, never because it is printed on a card.

## Adding a language

See [languages.md](languages.md) and [ADR 0010](decisions/0010-language-pack-plugins.md).
A language pack (`src/pii_guard/languages/<code>/`) contributes rules, a vault inflection
matcher if the language inflects names, LLM prompt notes, eval surface forms if it has stem
changes, a smoke fixture set, and a table in this file. Every piece is optional and falls back to language-independent behaviour; the
NER and LLM passes are multilingual and are re-measured, not rewritten.
