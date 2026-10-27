// SMS versions of the alerts, as a resident would receive them.
//
// The Twi text is a DRAFT written by an AI. Have a native Twi speaker check and
// correct it before showing it to anyone: wording in a flood warning has to be
// clear and natural. All Twi wording lives in this file.

import type { Alert, Level } from "./types";

export type Language = "en" | "tw";

export const LANGUAGES: Record<Language, string> = { en: "English", tw: "Twi" };

export const SENDER = "S2R ALERT";

const LEVEL_WORD: Record<Language, Record<Level, string>> = {
  en: { low: "LOW", medium: "MEDIUM", high: "HIGH" },
  tw: { low: "KAKRA", medium: "MFINIMFINI", high: "KƐSEƐ" },
};

export function smsText(alert: Alert, lang: Language): string {
  const level = LEVEL_WORD[lang][alert.level];
  const mm = Math.round(alert.acc_1h);
  const { name, eta_min: eta } = alert;
  if (lang === "en") {
    return alert.kind === "forecast"
      ? `WARNING: ${level} flood risk in ${name} in about ${eta} min. ${mm}mm of rain expected in the next hour. Clear drains, keep off low roads.`
      : `ALERT: ${level} flood risk in ${name} now. ${mm}mm of rain in the last hour. Keep away from drains and low roads.`;
  }
  return alert.kind === "forecast"
    ? `KƆKƆBƆ: Nsuyiri asiane ${level} reba ${name} wɔ simma ${eta} mu. Nsuo ${mm}mm bɛtɔ dɔnhwerew a ɛreba no mu. Monsiesie gota, montwe mo ho mfi mmeae a ɛda fam.`
    : `KƆKƆBƆ: Nsuyiri asiane ${level} wɔ ${name} seesei. Nsuo ${mm}mm atɔ dɔnhwerew a atwam no mu. Montwe mo ho mfi gota ne mmeae a ɛda fam.`;
}

// GSM 03.38 basic character set. Any other character (Twi ɛ and ɔ included)
// forces the whole message into UCS-2, which fits 70 characters per SMS instead of 160.
const GSM7 =
  "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡" +
  "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
const GSM7_EXTENDED = "^{}\\[~]|€"; // allowed, but each takes two characters

export interface SmsSize {
  encoding: "GSM-7" | "UCS-2";
  length: number;
  parts: number;
}

export function smsSize(text: string): SmsSize {
  const chars = [...text];
  if (chars.every((c) => GSM7.includes(c) || GSM7_EXTENDED.includes(c))) {
    const length = chars.reduce((n, c) => n + (GSM7_EXTENDED.includes(c) ? 2 : 1), 0);
    return { encoding: "GSM-7", length, parts: length <= 160 ? 1 : Math.ceil(length / 153) };
  }
  // UCS-2 counts UTF-16 code units; long messages lose 3 per part to the join header
  const length = text.length;
  return { encoding: "UCS-2", length, parts: length <= 70 ? 1 : Math.ceil(length / 67) };
}
