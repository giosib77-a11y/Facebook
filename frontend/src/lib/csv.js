/* CSV ექსპორტი — გადმოტანილია admin.js-იდან */

function cell(v) {
  let s = v == null ? "" : String(v);
  // ⚠️ CSV formula injection (რევიუ P2-10): Excel/Sheets ასეთი სიმბოლოთი დაწყებულ
  // უჯრას ფორმულად აღიქვამს და ფაილის გახსნისთანავე ასრულებს. პროდუქტის სახელს
  // გამყიდველი წერს, ექსპორტს კი ადმინი ხსნის — ანუ ეს გამყიდვლიდან ადმინამდე
  // მიმავალი გზაა. წინ დასმული აპოსტროფი ამას ანეიტრალებს.
  // რიცხვებს განზრახ არ ვეხებით, თორემ „-5" გაფუჭდებოდა.
  if (/^[=+\-@\t\r]/.test(s) && !/^-?\d+([.,]\d+)?$/.test(s)) {
    s = "'" + s;
  }
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

export function toCSV(headers, rows) {
  const lines = [headers.map(cell).join(",")];
  rows.forEach((r) => lines.push(r.map(cell).join(",")));
  // ﻿ (BOM) — Excel-ში ქართული სწორად გამოჩნდეს. არ მოხსნა.
  return "﻿" + lines.join("\r\n");
}

export function downloadCSV(name, content) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function fmtDate(s) {
  try {
    return s ? new Date(s).toLocaleDateString("ka-GE") : "—";
  } catch {
    return "—";
  }
}
