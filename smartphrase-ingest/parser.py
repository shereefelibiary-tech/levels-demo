// SmartphraseParserBox.jsx
// Standalone SmartPhrase parsing UI + parser utilities.
// Usage:
// <SmartphraseParserBox
//   onApplyPatch={(patch, parsed) => setInputs(prev => ({ ...prev, ...patch }))}
//   onParsed={(parsed) => console.log(parsed)}
// />

import React, { useEffect, useMemo, useRef, useState } from "react";

/** -----------------------------
 *  Public Component
 *  ----------------------------- */
export default function SmartphraseParserBox({
  title = "Paste Epic SmartPhrase",
  initialText = "",
  autoParse = true,
  debounceMs = 500,
  onParsed,          // (parsed) => void
  onApplyPatch,      // (patch, parsed) => void
  className = "",
}) {
  const [raw, setRaw] = useState(initialText);
  const [parsed, setParsed] = useState(null);
  const [patch, setPatch] = useState(null);
  const [errors, setErrors] = useState([]);
  const [lastParsedAt, setLastParsedAt] = useState(null);

  const debounceTimer = useRef(null);

  const doParse = () => {
    const res = parseEpicSmartphrase(raw);
    setParsed(res.parsed);
    setPatch(res.patch);
    setErrors(res.errors);
    setLastParsedAt(new Date());

    if (onParsed) onParsed(res.parsed);
  };

  useEffect(() => {
    if (!autoParse) return;
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(doParse, debounceMs);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw, autoParse, debounceMs]);

  const prettyParsed = useMemo(() => JSON.stringify(parsed ?? {}, null, 2), [parsed]);
  const prettyPatch = useMemo(() => JSON.stringify(patch ?? {}, null, 2), [patch]);

  return (
    <div className={className} style={styles.card}>
      <div style={styles.headerRow}>
        <div>
          <div style={styles.title}>{title}</div>
          <div style={styles.subtle}>
            Paste the rendered Epic SmartPhrase output here. This module only parses + emits a patch.
          </div>
        </div>
        <div style={styles.headerActions}>
          <button style={styles.btn} onClick={doParse}>Parse</button>
          <button
            style={{ ...styles.btn, ...(patch && Object.keys(patch).length ? {} : styles.btnDisabled) }}
            onClick={() => patch && onApplyPatch && onApplyPatch(patch, parsed)}
            disabled={!patch || Object.keys(patch).length === 0 || !onApplyPatch}
            title={!onApplyPatch ? "Provide onApplyPatch prop to enable" : "Apply patch to your app state"}
          >
            Apply
          </button>
        </div>
      </div>

      <textarea
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder="Paste SmartPhrase output…"
        rows={14}
        style={styles.textarea}
      />

      <div style={styles.metaRow}>
        <div style={styles.metaItem}>
          <strong>Status:</strong>{" "}
          {raw.trim().length === 0
            ? "Waiting for paste"
            : errors.length
              ? "Parsed with warnings"
              : "Parsed"}
        </div>
        <div style={styles.metaItem}>
          <strong>Last parsed:</strong>{" "}
          {lastParsedAt ? lastParsedAt.toLocaleString() : "—"}
        </div>
        <div style={styles.metaItem}>
          <strong>Chars:</strong> {raw.length}
        </div>
      </div>

      {errors.length > 0 && (
        <div style={styles.warnBox}>
          <div style={styles.warnTitle}>Warnings</div>
          <ul style={styles.warnList}>
            {errors.map((e, idx) => <li key={idx}>{e}</li>)}
          </ul>
        </div>
      )}

      <div style={styles.splitRow}>
        <div style={styles.panel}>
          <div style={styles.panelTitle}>Parsed (normalized)</div>
          <pre style={styles.pre}>{prettyParsed}</pre>
          <button style={styles.smallBtn} onClick={() => copyToClipboard(prettyParsed)}>
            Copy parsed JSON
          </button>
        </div>

        <div style={styles.panel}>
          <div style={styles.panelTitle}>Patch (apply to your app state)</div>
          <pre style={styles.pre}>{prettyPatch}</pre>
          <button style={styles.smallBtn} onClick={() => copyToClipboard(prettyPatch)}>
            Copy patch JSON
          </button>
        </div>
      </div>

      <details style={styles.details}>
        <summary style={styles.detailsSummary}>How to integrate</summary>
        <div style={styles.detailsBody}>
          <div style={styles.codeLabel}>Minimal integration example</div>
          <pre style={styles.pre}>
{`<SmartphraseParserBox
  onApplyPatch={(patch) => setInputs(prev => ({ ...prev, ...patch }))}
  onParsed={(parsed) => console.log("Parsed:", parsed)}
/>`}
          </pre>
          <div style={styles.subtle}>
            Tip: if you want “don’t overwrite user-changed fields”, apply patch selectively in your app.
          </div>
        </div>
      </details>
    </div>
  );
}

/** -----------------------------
 *  Main parser (public)
 *  ----------------------------- */
export function parseEpicSmartphrase(text) {
  const errors = [];
  const raw = normalize(text);

  // Merge multiple parsers (ASCVD block + label:value sections)
  const ascvd = parseEpicAscvdBlock(raw);
  const labeled = parseLabelValueTemplate(raw);

  // Combine into one normalized parsed object (labeled has priority where more specific)
  const parsed = {
    // ASCVD risk block
    ...ascvd,

    // General template fields
    ...labeled,

    // Keep raw for debugging if you want (comment out if you don’t)
    _rawLength: raw.length,
  };

  // Patch = a generic mapping you can apply directly if your state keys match these.
  // If your app uses different key names/enums, convert it in your app layer or tweak buildPatch().
  const patch = buildPatch(parsed, errors);

  // Friendly warnings when key data missing
  if (raw && parsed.ascvd10y == null && raw.includes("10-year ASCVD risk")) {
    errors.push("ASCVD block detected, but risk % was not parsed (format changed?).");
  }
  if (raw && parsed.sbp == null && raw.match(/Blood pressure|Systolic Blood Pressure/i)) {
    errors.push("BP appears present, but systolic value was not parsed.");
  }

  return { parsed, patch, errors };
}

/** -----------------------------
 *  Parser 1: Epic ASCVD Risk block
 *  (the block you pasted)
 *  ----------------------------- */
export function parseEpicAscvdBlock(text) {
  const out = {
    ascvd10y: null,          // number, e.g. 8.3
    age: null,
    sex: null,              // "female"|"male"|string
    africanAmerican: null,  // boolean
    diabetes: null,         // boolean
    smoker: null,           // boolean
    sbp: null,              // number
    bpTreated: null,        // boolean
    hdl: null,              // number
    totalChol: null,        // number
  };

  const riskMatch = text.match(/10-year ASCVD risk score.*?is:\s*([0-9]+(\.[0-9]+)?)\s*%/i);
  if (riskMatch) out.ascvd10y = Number(riskMatch[1]);

  out.age = parseNumberLoose(getLineValue(text, "Age"));

  const sexVal = getLineValue(text, "Clinically relevant sex");
  if (sexVal) out.sex = normalizeSex(sexVal);

  out.africanAmerican = parseYesNo(getLineValue(text, "Is Non-Hispanic African American"));
  out.diabetes = parseYesNo(getLineValue(text, "Diabetic"));
  out.smoker = parseYesNo(getLineValue(text, "Tobacco smoker"));

  out.sbp = parseNumberLoose(getLineValue(text, "Systolic Blood Pressure"));
  out.bpTreated = parseYesNo(getLineValue(text, "Is BP treated"));

  out.hdl = parseNumberLoose(getLineValue(text, "HDL Cholesterol"));
  out.totalChol = parseNumberLoose(getLineValue(text, "Total Cholesterol"));

  return out;
}

/** -----------------------------
 *  Parser 2: Your label:value template
 *  (works once Epic renders smartlinks into values)
 *  ----------------------------- */
export function parseLabelValueTemplate(text) {
  const out = {
    // demographics
    age: null,
    sex: null,
    race: null,
    smokingStatus: null,

    // vitals
    sbp: null,
    dbp: null,

    // labs
    a1c: null,
    ldl: null,
    hdl: null,
    totalChol: null,
    apob: null,
    lpa: null,
    hscrp: null,
    egfr: null,
    uacr: null,

    // imaging
    cac: null,

    // risk
    ascvd10y: null,
  };

  // Simple direct "Label: value" matches from your template
  const age = getLineValue(text, "Age");
  if (age) out.age = parseNumberLoose(age);

  const sex = getLineValue(text, "Sex");
  if (sex) out.sex = normalizeSex(sex);

  out.race = getLineValue(text, "Race/Ethnicity");
  out.smokingStatus = getLineValue(text, "Smoking status");

  const bpLine = getLineValue(text, "Blood pressure \\(most recent\\)");
  if (bpLine) {
    const bp = parseBP(bpLine);
    out.sbp = bp.sbp;
    out.dbp = bp.dbp;
  }

  // Labs (common)
  out.a1c = parseNumberLoose(getLineValue(text, "A1c"));
  out.apob = parseNumberLoose(getLineValue(text, "ApoB"));
  out.lpa = parseNumberLoose(getLineValue(text, "Lp\\(a\\)"));
  out.hscrp = parseNumberLoose(getLineValue(text, "hsCRP"));
  out.egfr = parseNumberLoose(getLineValue(text, "eGFR"));

  // Urine ACR can be messy; this catches "Urine ACR: 42 mg/g" etc.
  const uacrLine = getLineValue(text, "Urine ACR");
  if (uacrLine) out.uacr = parseNumberLoose(uacrLine);

  // CAC (if you later replace *** with a real value)
  const cacLine = getLineValue(text, "Coronary artery calcium \\(CAC\\) score");
  if (cacLine) out.cac = parseNumberLoose(cacLine);

  // If a lipid panel prints as lines like "Total Cholesterol 227" etc,
  // attempt a broad scrape:
  const tc = findNumberNear(text, /(Total Cholesterol|Cholesterol, Total|CHOL)\b/i);
  if (tc != null) out.totalChol = out.totalChol ?? tc;

  const hdl = findNumberNear(text, /\bHDL\b/i);
  if (hdl != null) out.hdl = out.hdl ?? hdl;

  const ldl = findNumberNear(text, /\bLDL\b/i);
  if (ldl != null) out.ldl = out.ldl ?? ldl;

  return out;
}

/** -----------------------------
 *  Patch builder
 *  (generic, tweak keys to match your app)
 *  ----------------------------- */
export function buildPatch(p, errors = []) {
  const patch = {};

  // Numeric fields
  if (p.age != null) patch.age = p.age;
  if (p.sbp != null) patch.sbp = p.sbp;
  if (p.dbp != null) patch.dbp = p.dbp;

  if (p.totalChol != null) patch.totalChol = p.totalChol;
  if (p.hdl != null) patch.hdl = p.hdl;
  if (p.ldl != null) patch.ldl = p.ldl;

  if (p.a1c != null) patch.a1c = p.a1c;
  if (p.apob != null) patch.apob = p.apob;
  if (p.lpa != null) patch.lpa = p.lpa;
  if (p.hscrp != null) patch.hscrp = p.hscrp;
  if (p.egfr != null) patch.egfr = p.egfr;
  if (p.uacr != null) patch.uacr = p.uacr;

  if (p.cac != null) patch.cac = p.cac;

  if (p.ascvd10y != null) patch.ascvd10y = p.ascvd10y;

  // Enums / booleans -> radios (store however you like)
  if (p.sex) patch.sex = normalizeSex(p.sex);

  // Smoking mapping (you can expand this)
  if (p.smoker != null) {
    patch.smoking = p.smoker ? "current" : "no";
  } else if (p.smokingStatus) {
    const t = p.smokingStatus.toLowerCase();
    if (t.includes("current")) patch.smoking = "current";
    else if (t.includes("former")) patch.smoking = "former";
    else if (t.includes("never")) patch.smoking = "never";
  }

  // Diabetes automation rule (your earlier requirement)
  // If A1c >= 6.5, force diabetes=yes regardless of "Diabetic: No" in the risk block.
  if (p.a1c != null && p.a1c >= 6.5) {
    patch.diabetes = "yes";
  } else if (p.diabetes != null) {
    patch.diabetes = p.diabetes ? "yes" : "no";
  }

  // BP treated
  if (p.bpTreated != null) patch.bpTreated = p.bpTreated ? "yes" : "no";

  // Race shortcut from ASCVD block (AA yes/no only)
  if (p.africanAmerican === true) patch.race = patch.race ?? "black";

  // Sanity checks / warnings
  if (patch.sbp != null && (patch.sbp < 60 || patch.sbp > 260)) {
    errors.push(`SBP parsed as ${patch.sbp}, which looks out of range.`);
  }
  if (patch.a1c != null && (patch.a1c < 3 || patch.a1c > 20)) {
    errors.push(`A1c parsed as ${patch.a1c}, which looks out of range.`);
  }

  return patch;
}

/** -----------------------------
 *  Helpers
 *  ----------------------------- */
function normalize(s) {
  return (s ?? "").toString();
}

function normalizeSex(sexVal) {
  const t = normalize(sexVal).trim().toLowerCase();
  if (t.includes("female")) return "female";
  if (t.includes("male")) return "male";
  return t;
}

function parseNumberLoose(s) {
  if (!s) return null;
  const m = normalize(s).replace(/,/g, "").match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : null;
}

function parseYesNo(s) {
  if (!s) return null;
  const t = normalize(s).trim().toLowerCase();
  if (t === "yes" || t.startsWith("yes")) return true;
  if (t === "no" || t.startsWith("no")) return false;
  return null;
}

function getLineValue(text, label) {
  // Works for both flush-left and indented lines: "Label: value"
  const re = new RegExp(`^\\s*${label}\\s*:\\s*(.+?)\\s*$`, "im");
  const m = normalize(text).match(re);
  return m ? m[1].trim() : null;
}

function parseBP(bpStr) {
  if (!bpStr) return { sbp: null, dbp: null };
  const m = normalize(bpStr).match(/(\d{2,3})\s*\/\s*(\d{2,3})/);
  return m ? { sbp: Number(m[1]), dbp: Number(m[2]) } : { sbp: null, dbp: null };
}

function findNumberNear(text, labelRegex) {
  // Finds "LABEL ... <number>" on same line
  const lines = normalize(text).split(/\r?\n/);
  for (const line of lines) {
    if (!labelRegex.test(line)) continue;
    const n = parseNumberLoose(line);
    if (n != null) return n;
  }
  return null;
}

async function copyToClipboard(str) {
  try {
    await navigator.clipboard.writeText(str);
  } catch {
    // Fallback: do nothing (some environments block clipboard)
  }
}

/** -----------------------------
 *  Minimal inline styles
 *  (swap with your CSS/Tailwind if you want)
 *  ----------------------------- */
const styles = {
  card: {
    border: "1px solid #e5e7eb",
    borderRadius: 12,
    padding: 14,
    background: "#fff",
    maxWidth: 1100,
  },
  headerRow: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
    alignItems: "flex-start",
    marginBottom: 10,
  },
  title: { fontSize: 16, fontWeight: 700 },
  subtle: { fontSize: 12, color: "#6b7280", marginTop: 2 },
  headerActions: { display: "flex", gap: 8 },
  btn: {
    padding: "8px 10px",
    borderRadius: 10,
    border: "1px solid #d1d5db",
    background: "#f9fafb",
    cursor: "pointer",
    fontWeight: 600,
  },
  btnDisabled: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
  textarea: {
    width: "100%",
    borderRadius: 12,
    border: "1px solid #d1d5db",
    padding: 10,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    lineHeight: 1.35,
  },
  metaRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 14,
    marginTop: 10,
    fontSize: 12,
    color: "#374151",
  },
  metaItem: { },
  warnBox: {
    marginTop: 10,
    border: "1px solid #fbbf24",
    background: "#fffbeb",
    borderRadius: 12,
    padding: 10,
  },
  warnTitle: { fontWeight: 800, fontSize: 12, marginBottom: 6 },
  warnList: { margin: 0, paddingLeft: 18, fontSize: 12 },
  splitRow: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 12,
    marginTop: 12,
  },
  panel: {
    border: "1px solid #e5e7eb",
    borderRadius: 12,
    padding: 10,
    background: "#fafafa",
  },
  panelTitle: { fontWeight: 800, fontSize: 12, marginBottom: 6 },
  pre: {
    margin: 0,
    padding: 10,
    borderRadius: 10,
    border: "1px solid #e5e7eb",
    background: "#fff",
    maxHeight: 240,
    overflow: "auto",
    fontSize: 12,
  },
  smallBtn: {
    marginTop: 8,
    padding: "6px 8px",
    borderRadius: 10,
    border: "1px solid #d1d5db",
    background: "#fff",
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 12,
  },
  details: { marginTop: 12 },
  detailsSummary: { cursor: "pointer", fontWeight: 800, fontSize: 12 },
  detailsBody: { marginTop: 8 },
  codeLabel: { fontSize: 12, fontWeight: 700, marginBottom: 6 },
};
