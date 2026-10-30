# One placeholder for a name the NER cut inside -ék (2026-10-30)

LAB-1384, found on the LAB-1342 stacked-suffix documents. The NER often ends a Hungarian name
between the family or possessive suffix and the case ending: `Teszt Hajnáék|nál`,
`Minta Hubáé|val`, or it labels the whole word and the suffix trim cut only the case ending
(`Teszt Elekék|hez`). The vault then keyed `Teszt Hajnáék` as a person of its own, so one
person got two or three placeholders. Nothing leaked.

The detectors' suffix trim now reads such a span together with the rest of its word as one
stacked form and ends it at the name's stem, `Teszt Hajná|éknál` (lemma `Teszt Hajna`). A whole
word that ends in the chain (`Hajnáékat`, `Minta Hubáéit`) is trimmed only after a changed stem
(`Hajná` → `Hajna`) or a lexicon name; a name that ends in `-é` itself (`Máté`) is left alone.

Fast mode (rules + NER v2 base, local), same checkpoint as the
[LAB-1342 record](../../eval/results/runs/2026-10-28-lab-1342-inflection-fast.json)
*(ticket comment, LAB-1384)*:

| Set | Placeholder consistency | Multi-occurrence consistent | Leaked values | Over-masked |
|---|---:|---:|---:|---:|
| hu-inflection, before | 19 / 28 | 7 / 16 | 1 / 50 | 0 |
| hu-inflection, after | 21 / 28 | 9 / 16 | 1 / 50 | 0 |
| all `hu` fixtures, before | 419 / 434 | 62 / 71 | 4 / 457 | 3 |
| all `hu` fixtures, after | 421 / 434 | 64 / 71 | 4 / 457 | 3 |

Round trip stays 100 %. Left as is: `Gyakorló Tihaméréké` (an unknown name with no stem change
before a bare `-é` is not a safe cut) and the surname outside the placeholder when the NER
labels only the given name. Cost: none.
