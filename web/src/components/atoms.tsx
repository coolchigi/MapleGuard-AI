import React from "react";

/** A cited-to-source line: doc icon + monospace source string. */
export function Cite({ children }: { children: React.ReactNode }) {
  return (
    <span className="cite">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
        <path d="M14 2v6h6" />
      </svg>
      {children}
    </span>
  );
}

/** The COMPUTED · NOT ADJUDICATED wax stamp, rotated in the hero corner. */
export function Stamp() {
  return (
    <div style={{
      position: "absolute", right: 4, top: -14, transform: "rotate(-9deg)",
      border: "2.5px solid var(--maple)", borderRadius: 7, padding: "6px 12px",
      textAlign: "center", color: "var(--maple)", opacity: 0.85,
    }}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 13, fontWeight: 600, letterSpacing: "0.1em" }}>
        COMPUTED
      </div>
      <div style={{
        fontFamily: "var(--mono)", fontSize: 8, letterSpacing: "0.14em",
        borderTop: "1px solid var(--maple)", marginTop: 3, paddingTop: 2,
      }}>
        NOT ADJUDICATED
      </div>
    </div>
  );
}

/** Guilloche security-print pattern behind the hero number. */
export function Guilloche() {
  return (
    <svg className="guilloche" width="340" height="240" viewBox="0 0 340 240" aria-hidden
      style={{ position: "absolute", left: -14, top: -18, opacity: 0.07, pointerEvents: "none" }}>
      <defs>
        <pattern id="gw" width="42" height="42" patternUnits="userSpaceOnUse" patternTransform="rotate(12)">
          <path d="M0,21 Q10.5,3 21,21 T42,21" fill="none" stroke="#14110D" strokeWidth="1" />
        </pattern>
      </defs>
      <circle cx="150" cy="120" r="118" fill="none" stroke="#14110D" strokeWidth="1" />
      <circle cx="150" cy="120" r="92" fill="none" stroke="#14110D" strokeWidth="1" />
      <rect x="0" y="0" width="340" height="240" fill="url(#gw)" />
    </svg>
  );
}

/** The masthead: maple mark + wordmark, and an italic dated label on the right. */
export function Masthead({ label }: { label: string }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      paddingBottom: 13, borderBottom: "2px solid var(--ink)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--maple)"
          strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3c1.6 3 1 5 3 6.5C17.3 11.2 19 12 19 15a7 7 0 0 1-14 0c0-3 1.7-3.8 4-5.5C11 8 10.4 6 12 3Z" />
        </svg>
        <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: "0.22em" }}>
          MAPLEGUARD — EXPRESS ENTRY
        </span>
      </div>
      <span style={{ fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 14, color: "var(--muted)" }}>
        {label}
      </span>
    </div>
  );
}

/** Machine-readable-zone footer strip (passport signature). */
export function MrzStrip({ line1, line2, caption }: { line1: string; line2: string; caption: string }) {
  return (
    <>
      <div style={{
        margin: "30px -52px 0", background: "var(--ink)", color: "var(--panel)",
        fontFamily: "var(--mono)", fontSize: 14, letterSpacing: "0.2em",
        padding: "15px 52px", lineHeight: 1.8, overflowX: "auto",
      }}>
        <span style={{ whiteSpace: "nowrap" }}>{line1}</span><br />
        <span style={{ whiteSpace: "nowrap" }}>{line2}</span>
      </div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--muted-2)", padding: "10px 0 0", letterSpacing: "0.03em" }}>
        {caption}
      </div>
    </>
  );
}
