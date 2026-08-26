"use client";

import React, { useState } from "react";
import demo from "@/data/demo.json";
import type { DemoData } from "@/data/types";
import { PositionPanel } from "@/components/PositionPanel";
import { TimeMachine } from "@/components/TimeMachine";

const data = demo as DemoData;

type Tab = "position" | "time";

export default function Page() {
  const [tab, setTab] = useState<Tab>("position");

  return (
    <main className="stage">
      <nav className="tabs">
        <span className="tab-brand">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--maple)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3c1.6 3 1 5 3 6.5C17.3 11.2 19 12 19 15a7 7 0 0 1-14 0c0-3 1.7-3.8 4-5.5C11 8 10.4 6 12 3Z" />
          </svg>
          MAPLEGUARD
        </span>
        <button className="tab" data-active={tab === "position"} onClick={() => setTab("position")}>
          POSITION
        </button>
        <button className="tab" data-active={tab === "time"} onClick={() => setTab("time")}>
          TIME MACHINE
        </button>
      </nav>

      {tab === "position" ? <PositionPanel data={data} /> : <TimeMachine data={data} />}
    </main>
  );
}
