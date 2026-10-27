// Fictional sample documents. Every name, address and identifier below is made
// up (ADR 0005); the identifiers carry valid checksums so the real rule
// detectors accept them, but none belongs to anyone.

export interface Sample {
  id: string;
  title: string;
  subtitle: string;
  language: "hu" | "en";
  /** What the user asks the model to do with the document. */
  task: string;
  text: string;
  /**
   * The simulated model answer. `{{value}}` marks a value from `text`; it is
   * replaced by that value's placeholder once the document has been masked,
   * which is what a model would echo back.
   */
  answer: string;
}

export const SAMPLES: Sample[] = [
  {
    id: "contract",
    title: "Adásvételi szerződés",
    subtitle: "Property sale contract",
    language: "hu",
    task: "Summarise the parties and the payment terms in English.",
    text: `ADÁSVÉTELI SZERZŐDÉS

amely létrejött egyrészről Bárdos Kinga (születési idő: 1978. március 14., adóazonosító jel: 8406144122, lakcím: 1137 Budapest, Pozsonyi út 38. 2/5.) mint eladó,

másrészről Varga Levente (született: 1985. november 2., személyi igazolvány száma: 482913KE, TAJ: 039812654, lakcím: 6720 Szeged, Kárász utca 11.) mint vevő között az alábbi feltételekkel:

1. Eladó kizárólagos tulajdonát képezi a Budapest XIII. kerület, belterület hrsz. 25784/0/A/12 alatt nyilvántartott lakás.
2. A vételár 68 500 000 Ft, amelyet Vevő a HU78 1177 3016 2048 5733 0000 0006 számú bankszámlára utal.
3. A szerződést Somogyi Ádám ügyvéd (Somogyi Ügyvédi Iroda, telefon: +36 30 555 0142, e-mail: somogyi.adam@example.com) ellenjegyzi.

Kelt: Budapest, 2026. október 20.`,
    answer: `Summary of the sale contract

• Seller: {{Bárdos Kinga}}, born {{1978. március 14.}}, living at {{1137 Budapest, Pozsonyi út 38. 2/5.}}
• Buyer: {{Varga Levente}}, ID card {{482913KE}}
• Property: the flat registered under parcel number {{25784/0/A/12}}
• Price: HUF 68,500,000, paid to {{HU78 1177 3016 2048 5733 0000 0006}}

Next step: {{Somogyi Ádám}} countersigns. You can reach him on {{+36 30 555 0142}}.`,
  },
  {
    id: "claim",
    title: "Kárbejelentő e-mail",
    subtitle: "Insurance claim email",
    language: "hu",
    task: "Turn this into a structured claim summary for the insurer.",
    text: `Tárgy: Kárbejelentés – AAB-123 rendszámú gépjármű

Tisztelt Ügyfélszolgálat!

Takács Gábor vagyok (szül. 1991. június 27., adóazonosító jel: 8454671188). 2026. október 18-án a 4025 Debrecen, Piac utca 52. előtt parkoló AAB-123 forgalmi rendszámú autómat egy SXE-482 rendszámú furgon megrongálta. A sofőr, Fehér Ilona elérhetősége: +36 20 555 0187.

Kérem, a kártérítést a 10405028-50880019-00000001 számlaszámra utalják. Visszahívást a +36 70 555 0123 számon vagy a takacs.gabor@example.org címen kérek.

Üdvözlettel:
Takács Gábor`,
    answer: `Claim summary

Policyholder {{Takács Gábor}} reports that the car {{AAB-123}} was damaged on 18 October 2026 while parked outside {{4025 Debrecen, Piac utca 52.}}

• Other vehicle: {{SXE-482}}, driven by {{Fehér Ilona}} ({{+36 20 555 0187}})
• Payout account: {{10405028-50880019-00000001}}
• Call back on {{+36 70 555 0123}} or write to {{takacs.gabor@example.org}}`,
  },
  {
    id: "referral",
    title: "Beutaló",
    subtitle: "Medical referral",
    language: "hu",
    task: "Write a short English handover note for the cardiology desk.",
    text: `BEUTALÓ – kardiológiai szakrendelésre

Beteg: Dr. Németh Zsófia
Született: 1985. november 2.
TAJ-szám: 210345771
Lakcím: 9022 Győr, Kálvária utca 7. 1/3.
Telefon: 06 30 555 0164

Panasz: terheléskor jelentkező mellkasi szorítás, két hete. A beteget Kerekes Ottótól, a háziorvostól (Győri Egészségközpont Kft., Cg. 08-09-123456) irányították hozzánk. A vizsgálatra hozzátartozója, Németh Bálint kíséri.

Kérjük, az eredményt a nemeth.zsofia@example.com címre is küldjék el.`,
    answer: `Handover note — cardiology

Patient {{Németh Zsófia}} (TAJ {{210345771}}, born {{1985. november 2.}}) reports chest tightness on exertion for two weeks. Referred by GP {{Kerekes Ottó}}; accompanied by {{Németh Bálint}}.

Please send the results to {{nemeth.zsofia@example.com}} and confirm the appointment on {{06 30 555 0164}}.`,
  },
  {
    id: "support",
    title: "Support ticket",
    subtitle: "English · customer email",
    language: "en",
    task: "Draft a short, polite reply that confirms the refund.",
    text: `Subject: Refund for order 4471 – please help

Hello,

my name is Jane Placeholder and I was charged twice for my order. You can reach me at jane.placeholder@example.net or on +44 20 7946 0958. Please refund the duplicate payment to my account GB33 BUKB 2020 1555 5555 55.

My colleague Sam Example (sam.example@example.org) placed the order for me from our office at 221 Example Street, London. He says Jane Placeholder's card was used by mistake.

Thanks,
Jane Placeholder`,
    answer: `Dear {{Jane Placeholder}},

Thank you for letting us know. We have refunded the duplicate payment to {{GB33 BUKB 2020 1555 5555 55}}; it should arrive within three working days. We have also sent a copy of this confirmation to {{sam.example@example.org}}.

If anything is unclear, we will call you on {{+44 20 7946 0958}}.`,
  },
];

export const DEFAULT_SAMPLE = SAMPLES[0]!;
