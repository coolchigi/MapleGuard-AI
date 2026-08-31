"use client";

/**
 * The form primitives, in the document's own visual language: ruled rows, a serif label on the
 * left, the control on the right, like a field on a printed application.
 *
 * They are deliberately dumb and controlled — every one takes `value` + `onChange` and holds no
 * state of its own, so `ProfileForm` remains the single owner of the working profile. Classes
 * (`.mg-*`) live in globals.css beside the rest of the sheet styling.
 */
import React, { useId } from "react";

export function Fieldset({
  code,
  title,
  hint,
  children,
}: {
  code: string;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="mg-fieldset">
      <legend className="mg-legend">
        <span className="mg-legend-code">{code}</span>
        {title}
      </legend>
      {hint && <p className="mg-hint">{hint}</p>}
      {children}
    </fieldset>
  );
}

function FieldShell({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mg-field" data-invalid={error ? "true" : undefined}>
      <div className="mg-field-label">
        <label htmlFor={htmlFor}>{label}</label>
        {hint && <span className="mg-field-hint">{hint}</span>}
        {error && (
          <span className="mg-field-error" role="alert">
            {error}
          </span>
        )}
      </div>
      <div className="mg-field-control">{children}</div>
    </div>
  );
}

export function SelectField<T extends string | number>({
  label,
  hint,
  error,
  value,
  options,
  onChange,
}: {
  label: string;
  hint?: string;
  error?: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const id = useId();
  // Round-trip through the option list rather than casting the raw string: it keeps the union
  // type honest and works for numeric values without a parseInt at every call site.
  const handle = (raw: string) => {
    const picked = options.find((o) => String(o.value) === raw);
    if (picked) onChange(picked.value);
  };

  return (
    <FieldShell label={label} hint={hint} error={error} htmlFor={id}>
      <select
        id={id}
        className="mg-select"
        value={String(value)}
        onChange={(e) => handle(e.target.value)}
        aria-invalid={error ? true : undefined}
      >
        {options.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

export function DateField({
  label,
  hint,
  error,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  error?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <FieldShell label={label} hint={hint} error={error} htmlFor={id}>
      <input
        id={id}
        type="date"
        className="mg-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
      />
    </FieldShell>
  );
}

export function ToggleField({
  label,
  hint,
  value,
  onChange,
  worth,
}: {
  label: string;
  hint?: string;
  value: boolean;
  onChange: (value: boolean) => void;
  /** What ticking this is worth on the grid, e.g. "+600". Shown as the row's right-hand figure. */
  worth?: string;
}) {
  const id = useId();
  return (
    <div className="mg-toggle">
      <input
        id={id}
        type="checkbox"
        className="mg-checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />
      <label htmlFor={id} className="mg-toggle-label">
        {label}
        {hint && <span className="mg-field-hint">{hint}</span>}
      </label>
      {worth && <span className="mg-toggle-worth">{worth}</span>}
    </div>
  );
}

/**
 * A CLB level per ability, with a "set all four" control above it.
 *
 * Most candidates hold one number in their head ("I got CLB 9"), so the even-set control is the
 * fast path; the per-ability selects are there because the grid genuinely scores each ability
 * separately and a real test result is rarely flat.
 */
export function LanguageGrid({
  title,
  hint,
  abilities,
  levels,
  value,
  onChange,
  error,
  disabled,
}: {
  title: string;
  hint?: string;
  abilities: { key: keyof T_Scores; label: string; short: string }[];
  levels: readonly number[];
  value: T_Scores;
  onChange: (value: T_Scores) => void;
  error?: string;
  disabled?: boolean;
}) {
  const allEqual = new Set(abilities.map(({ key }) => value[key])).size === 1;

  return (
    <div className="mg-langgrid" data-disabled={disabled ? "true" : undefined}>
      <div className="mg-langgrid-head">
        <span className="mg-langgrid-title">
          {title}
          {hint && <span className="mg-field-hint">{hint}</span>}
        </span>
        <span className="mg-langgrid-all">
          <label htmlFor={`${title}-all`}>Set all</label>
          <select
            id={`${title}-all`}
            className="mg-select mg-select-sm"
            disabled={disabled}
            value={allEqual ? String(value[abilities[0].key]) : ""}
            onChange={(e) => {
              const clb = Number(e.target.value);
              if (Number.isNaN(clb)) return;
              onChange(
                abilities.reduce(
                  (acc, { key }) => ({ ...acc, [key]: clb }),
                  {} as T_Scores,
                ),
              );
            }}
          >
            {!allEqual && <option value="">mixed</option>}
            {levels.map((clb) => (
              <option key={clb} value={String(clb)}>
                {clb === 0 ? "none" : `CLB ${clb}`}
              </option>
            ))}
          </select>
        </span>
      </div>

      <div className="mg-langgrid-abilities">
        {abilities.map(({ key, label, short }) => (
          <label key={String(key)} className="mg-ability">
            <span className="mg-ability-label" title={label}>
              {short}
            </span>
            <select
              className="mg-select mg-select-sm"
              disabled={disabled}
              value={String(value[key])}
              aria-label={label}
              onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) })}
            >
              {levels.map((clb) => (
                <option key={clb} value={String(clb)}>
                  {clb === 0 ? "—" : clb}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      {error && (
        <div className="mg-field-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

/** Local alias so LanguageGrid stays readable without importing the domain type into a file of
 *  otherwise domain-free primitives. */
type T_Scores = { speaking: number; listening: number; reading: number; writing: number };
