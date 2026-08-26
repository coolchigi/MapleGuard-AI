export type LineItem = {
  label: string;
  meta?: string;
  points: number;
  muted?: boolean;
};

export type Lever = { label: string; points: string };

export type Category = {
  code: string;
  label: string;
  cap: number;
  subtotal: number;
  items?: LineItem[];
  levers?: Lever[];
  note: string;
  cite: string;
};

export type TrajectoryPoint = { date: string; dateHuman: string; total: number };

export type Cliff = {
  date: string;
  dateHuman: string;
  kind: "age" | "test_expiry";
  delta: number;
  total: number;
  label: string;
};

export type DemoData = {
  generatedBy: string;
  asOf: string;
  asOfHuman: string;
  position: {
    total: number;
    core: number;
    skillTransfer: number;
    additional: number;
    categories: Category[];
  };
  lastDraw: { score: number; delta: number; cite: string; date: string };
  trajectory: {
    points: TrajectoryPoint[];
    cliffs: Cliff[];
    testExpiry: string | null;
    testExpiryHuman: string | null;
    testExpiryDelta: number | null;
    daysToExpiry: number | null;
    endTotal: number;
  };
};
