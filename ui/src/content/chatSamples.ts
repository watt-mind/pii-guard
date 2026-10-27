// Fictional chat prompts for the Chat screen (ADR 0005). Every name, address and number is
// made up; the IBAN and phone formats are valid so the rule detectors find them.

export interface ChatSample {
  id: string;
  language: "hu" | "en";
  label: string;
  text: string;
}

export const CHAT_SAMPLES: ChatSample[] = [
  {
    id: "hu-letter",
    language: "hu",
    label: "Letter (Hungarian)",
    text: "Szia! Teszt Elek vagyok, e-mail: teszt.elek@example.com, telefon: +36 30 555 0142. Írj egy rövid, udvarias levelet Minta Máriának, hogy a szerződést jövő kedden aláírnánk a 1137 Budapest, Pozsonyi út 38. alatti irodában.",
  },
  {
    id: "en-refund",
    language: "en",
    label: "Refund (English)",
    text: "Hi, I'm Jane Placeholder (jane.placeholder@example.net, +44 20 7946 0958). Please draft a two-sentence email to Sam Example asking him to refund the deposit to GB33 BUKB 2020 1555 5555 55.",
  },
];
