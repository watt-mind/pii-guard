# Why it matters in the EU

> **Not legal advice.** This page maps PII Guard's technical behavior to the EU rules a data
> protection officer (DPO) will ask about. It says what each rule requires, with a link to the
> primary text, and what PII Guard does that is relevant. Whether your processing is lawful is
> your assessment, with your own counsel. Checked against the primary sources on 2026-10-29.

European teams building AI agents run into the same question: the useful data (a case file, an
HR folder, a loan application) is personal data, and the best models are often run by providers
outside the EU. PII Guard takes the personal values out of the request before it leaves, keeps
the mapping back to them, and puts them back in the answer. The rules below are why that matters.

## Contents

- [Minimization and pseudonymization](#minimization-and-pseudonymization)
- [Pseudonymized data and the recipient (CJEU, EDPS v SRB)](#pseudonymized-data-and-the-recipient-cjeu-edps-v-srb)
- [International transfers](#international-transfers)
- [Sector rules](#sector-rules)
- [The EU AI Act, briefly](#the-eu-ai-act-briefly)
- [What PII Guard does, as a technical measure](#what-pii-guard-does-as-a-technical-measure)
- [What we don't claim](#what-we-dont-claim)
- [Live in 3 steps](#live-in-3-steps)
- [Sources](#sources)
- [Landing copy](#landing-copy)

## Minimization and pseudonymization

All from the GDPR, [Regulation (EU) 2016/679][gdpr]:

| Rule | What it says (paraphrased; quoted terms are the Regulation's own) | Why it is relevant |
|---|---|---|
| **Art. 5(1)(c)**, data minimization | Personal data shall be "adequate, relevant and limited to what is necessary" for the purposes. | A model drafting a letter rarely needs the real name, IBAN or ID number to do it. |
| **Art. 25(1)**, data protection by design | The controller implements appropriate technical and organizational measures, "such as pseudonymisation", designed to implement principles "such as data minimisation". | Pseudonymization is the Regulation's own example of a by-design measure. |
| **Art. 25(2)**, by default | By default, only personal data necessary for each specific purpose are processed, including as to their "accessibility". | Masking by default limits who can read the values: the model provider gets placeholders. |
| **Art. 32(1)(a)**, security of processing | Appropriate measures include "the pseudonymisation and encryption of personal data". | Pseudonymization is also named as a security measure. |
| **Recital 78** | By-design measures could consist of "pseudonymising personal data as soon as possible". | PII Guard pseudonymizes at the point the request leaves your application. |
| **Art. 4(5)**, definition | Pseudonymization: data "can no longer be attributed to a specific data subject without the use of additional information", provided that information "is kept separately" under technical and organizational measures. | The placeholder mapping is that additional information, and it is kept apart from what the model receives (see [below](#what-pii-guard-does-as-a-technical-measure)). |
| **Recital 26** | Pseudonymized data that could be attributed to a person with additional information "should be considered to be information on an identifiable natural person"; the GDPR does not apply to anonymous information. | **Pseudonymized is not anonymous.** For whoever holds the mapping, the data stay personal data. |

## Pseudonymized data and the recipient (CJEU, EDPS v SRB)

On 4 September 2025 the Court of Justice decided **Case C‑413/23 P, *EDPS v SRB***
([judgment on EUR-Lex][srb], [case file on curia][srb-curia]). The case concerned the EU
institutions' data protection regulation, Regulation (EU) 2018/1725, whose definition of
personal data the Court called "essentially identical" to Art. 4(1) GDPR (para. 52). The Court
held:

- Pseudonymized data "must not be regarded as constituting, in all cases and for every person,
  personal data", because pseudonymization may, depending on the circumstances, effectively
  prevent persons other than the controller from identifying the data subject, so that "for
  them" the person is not identifiable (para. 86). Identifiability is examined in relation to
  each person who processes the information (para. 96).
- But if it cannot be ruled out that the recipient has means reasonably likely to re-identify,
  for example by cross-checking with other data it holds, the data subject must be regarded as
  identifiable for that transfer and the recipient's processing (para. 85).
- The controller's own duty to inform data subjects about recipients is assessed from the
  controller's point of view, at the time of collection (para. 111). The controller's
  obligations do not go away because the recipient only sees pseudonyms.

What this means for PII Guard, stated carefully:

- **For you (and whoever holds the placeholder mapping), the masked request is still personal
  data.** You hold the means to re-identify it.
- **For the model provider, what it receives *may* not be personal data *for that recipient***,
  if it has no reasonable means to re-identify: it never gets the mapping, and the placeholders
  are keyed (see [ADR 0007](decisions/0007-keyed-pseudonyms.md)). That is a case-by-case
  assessment, not a property PII Guard can guarantee. A value detection misses, or context such
  as "the only female judge at the regional court", can identify someone without a name
  ([privacy model](privacy-model.md#explicit-non-guarantees)).
- The EDPB's [Guidelines 01/2025 on pseudonymisation][edpb] (adopted 16 January 2025, version
  for public consultation) predate the judgment and take a broader view: pseudonymized data
  remain personal "if pseudonymised data and additional information are not in the hands of the
  same person". Read both.

## International transfers

GDPR **Chapter V** ([Art. 44 ff.][gdpr]) allows a transfer of personal data to a third country
"only if" the Chapter's conditions are met: an adequacy decision (Art. 45), appropriate
safeguards such as standard contractual clauses (Art. 46), or a listed derogation. This is the
usual DPO concern with a model provider outside the EU.

For the United States, the Commission adopted an adequacy decision for the **EU–US Data Privacy
Framework** ([Implementing Decision (EU) 2023/1795][dpf], 10 July 2023); it covers organizations
that participate in the Framework. Whether a given provider is covered, and whether your
transfer is lawful, is not something this page decides.

PII Guard's part is narrower: it reduces what crosses the border. The provider receives
placeholders instead of names, IDs and faces, and the mapping does not travel with them. Whether
the masked request is still a transfer of personal data turns on the recipient's means to
re-identify ([above](#pseudonymized-data-and-the-recipient-cjeu-edps-v-srb)).

## Sector rules

- **Lawyers.** Professional secrecy is set by national law and bar rules; the GDPR itself
  recognizes such obligations of secrecy under Union or Member State law (Art. 90, [GDPR][gdpr]).
  Check your own bar's rules on outside service providers.
- **HR and employment data.** Member States may adopt more specific rules for employees'
  personal data in the employment context (Art. 88, [GDPR][gdpr]), so expect national rules on
  top of the GDPR.
- **Finance.** The Digital Operational Resilience Act, [Regulation (EU) 2022/2554][dora] (DORA),
  applies from 17 January 2025 (Art. 64). Financial entities manage ICT third-party risk as part
  of their ICT risk framework and remain "fully responsible" for compliance when they use ICT
  services (Art. 28(1)); contracts must state the regions or countries where data is processed
  (Art. 30(2)(b)).

## The EU AI Act, briefly

The AI Act, [Regulation (EU) 2024/1689][aiact], regulates AI systems by risk. Two parts touch
the use cases PII Guard serves:

- **Art. 10**, data and data governance: training, validation and testing data for **high-risk**
  AI systems must meet quality criteria and be subject to data governance practices.
- **Annex III, point 4**: AI systems for recruitment and selection, and for decisions on
  promotion, termination, task allocation and monitoring of workers, are high-risk.

**Timeline.** Chapters I and II (general provisions and prohibited practices) apply from
2 February 2025, except a few prohibitions the Omnibus added, from 2 December 2026; the
general-purpose AI rules (Chapter V) from 2 August 2025; the general date of application is 2 August 2026
(Art. 113). The Digital Omnibus on AI, [Regulation (EU) 2026/1744][omnibus] (published 24 July
2026), moved the high-risk obligations of Chapter III, Sections 1 to 3: to **2 December 2027**
for Annex III systems and to **2 August 2028** for Annex I systems.

**PII Guard is not an AI Act compliance tool.** It does not classify your system, assess its
risk or produce the documentation the Act requires. It masks personal data in requests to a
model, which may support your data governance; that is all.

## What PII Guard does, as a technical measure

Each point links to the repository document it rests on.

| Behavior | Where it is documented |
|---|---|
| **Masked before it leaves.** Names, addresses, IDs and other values in messages, tool definitions, tool-call arguments and tool results are replaced by placeholders before the request goes upstream; faces, ID photos and signatures in inline images are covered. | [Gateway](architecture-gateway.md), [README](../README.md#built-for-agents-tool-calls-and-streaming) |
| **Reversible placeholders, mapping kept with the guard.** Placeholders are keyed HMACs, unlinkable across tenants; the mapping stays in the guard's vault and is used to restore the answer, also mid-stream. Self-hosted, that vault is on your infrastructure; in the hosted preview it is an owner-scoped vault with a sliding one-hour session. | [Privacy model](privacy-model.md), [ADR 0007](decisions/0007-keyed-pseudonyms.md), [hosted retention](hosted.md) |
| **EU-hosted preview.** The hosted service at guard.watt-mind.com runs on Azure in Sweden Central. Its process receives the original input, so it is inside your trust boundary; the downstream model gets masked text. The downstream provider's terms do not by themselves establish EU-only processing. | [Hosted](hosted.md#dedicated-azure-deployment), [privacy model](privacy-model.md#hosted-service-boundary) |
| **Self-host option.** Run it yourself (`pii-guard up`, `make demo`, Docker Compose); with the `local-only` detection profile, detection, OCR and image masking run on that machine and only the masked request goes to the model. | [README](../README.md#try-it), [privacy model](privacy-model.md#local-only-detection-boundary) |
| **Logs and the outbound re-check.** Every call through the gateway is in Logs with its entity types, timing and outbound check result. Before anything goes upstream, the gateway searches the masked request for every real value the session knows; if one survives, the request is refused with `422 outbound_check_failed` and nothing is sent. Logs hold types, counts and placeholder ids, not raw values. | [Outbound re-check](architecture-gateway.md#outbound-re-check), [traffic record](operations.md), [privacy model](privacy-model.md#explicit-non-guarantees) |

The outbound re-check catches values the session already knows. It cannot catch a value that
detection never found; the published leak rates measure how often that happens
([benchmarks](benchmarks.md)).

## What we don't claim

- **Not legal advice.** Nothing here is a legal opinion on your processing.
- **It does not make you GDPR or AI Act compliant.** It is one technical measure among the many
  a controller needs.
- **It does not replace a DPIA, a data processing agreement or a transfer assessment.** You
  still need your records, your lawful basis, your contracts with providers and your own risk
  assessment.
- **It is not anonymization.** Pseudonymized data remain personal data for whoever can
  re-identify them (Recital 26), and detection is not perfect.
- **GDPR Art. 9 special categories are out of scope.** PII Guard has no entity types for health
  data, ethnic origin, religion, political opinions or sexual orientation, so such content in free
  text passes through as written ([evaluation](evaluation.md)). Do not rely on it for them.

## Live in 3 steps

1. **Change one base URL.** Point your OpenAI-compatible client or agent at the gateway; your
   code, prompts and tools stay as they are ([README](../README.md#built-for-agents-tool-calls-and-streaming)).
2. **Masking and restoring are automatic.** Streamed answers, tool calls and inline images are
   handled with no extra code ([gateway](architecture-gateway.md)).
3. **Watch it in Logs.** Every request is listed with what was masked and its outbound check
   result, `passed` or `blocked` ([outbound re-check](architecture-gateway.md#outbound-re-check)).

## Sources

All fetched and checked on 2026-10-29 (the Official Journal texts through the EU Publications
Office, which serves the same documents as EUR-Lex).

- [GDPR, Regulation (EU) 2016/679][gdpr], OJ L 119, 4.5.2016: Art. 4(5), 5(1)(c), 25, 32,
  44–46, 88, 90; Recitals 26, 78.
- [Judgment of 4 September 2025, *EDPS v SRB*, C‑413/23 P][srb], paras. 52, 85, 86, 96, 111;
  [curia case file][srb-curia].
- [EDPB, Guidelines 01/2025 on Pseudonymisation][edpb], version for public consultation.
- [Commission Implementing Decision (EU) 2023/1795][dpf] (EU–US Data Privacy Framework).
- [DORA, Regulation (EU) 2022/2554][dora]: Art. 28, 30, 64.
- [AI Act, Regulation (EU) 2024/1689][aiact]: Art. 10, 113, Annex III.
- [Digital Omnibus on AI, Regulation (EU) 2026/1744][omnibus]: amends Art. 113.

[gdpr]: https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng
[srb]: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62023CJ0413
[srb-curia]: https://curia.europa.eu/juris/liste.jsf?num=C-413/23
[edpb]: https://www.edpb.europa.eu/our-work-tools/documents/public-consultations/2025/guidelines-012025-pseudonymisation_en
[dpf]: https://eur-lex.europa.eu/eli/dec_impl/2023/1795/oj/eng
[dora]: https://eur-lex.europa.eu/eli/reg/2022/2554/oj/eng
[aiact]: https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng
[omnibus]: https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng

## Landing copy

Vetted short copy for the landing page's "Why Europe" section. Keep the wording; each card links
to its section here.

**Minimize before you send** ([section](#minimization-and-pseudonymization))
GDPR asks for data minimization and names pseudonymization as a design and security measure
(Art. 5, 25, 32). PII Guard swaps names and IDs for placeholders before the prompt leaves.

**Less personal data crossing borders** ([section](#international-transfers))
Non-EU model providers raise Chapter V transfer questions. The model receives placeholders; the
mapping back to real values stays with your guard, self-hosted or in our EU-hosted preview.

**Built for regulated work** ([section](#sector-rules))
Lawyers' secrecy, employee data (GDPR Art. 88) and DORA's ICT third-party rules for finance all
bear on what reaches an outside vendor. Every call is logged and re-checked.

**Disclaimer:** A technical measure, not legal advice: pseudonymized data can still be personal
data, and you still need your own DPIA and agreements. [What we don't claim](#what-we-dont-claim).

**3-step strip:** Change one base URL. → Masking and restoring happen automatically: streaming,
tool calls, images. → See every request in Logs, with its outbound check result.
