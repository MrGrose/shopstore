import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type TouchEvent,
} from "react";

type RangeThumb = "lo" | "hi";

function parsePrice(value: unknown): number | null {
  const n = Number(String(value ?? "").replace(/\s/g, ""));
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : null;
}

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

function resolveBounds(
  boundsMin: unknown,
  boundsMax: unknown,
): { minBound: number; maxBound: number } | null {
  const minBound = parsePrice(boundsMin);
  let maxBound = parsePrice(boundsMax);
  if (minBound == null || maxBound == null) return null;
  if (maxBound <= minBound) maxBound = minBound + 1_000;
  return { minBound, maxBound };
}

function clamp(n: number, min: number, max: number) {
  return Math.min(Math.max(n, min), max);
}

/** Keep in-progress thumb positions when facet bounds refetch before both prices hit URL. */

export function isCatalogPriceSliderFiltered(
  lo: number,
  hi: number,
  bounds: { minBound: number; maxBound: number },
  priceMin: string,
  priceMax: string,
): boolean {
  if (priceMin.trim() || priceMax.trim()) return true;
  return lo > bounds.minBound || hi < bounds.maxBound;
}

export function mergeCatalogPriceSliderRange(
  prev: [number, number],
  fromFilters: [number, number],
  priceMin: string,
  priceMax: string,
): [number, number] {
  if (!priceMin.trim() && !priceMax.trim()) {
    return fromFilters;
  }
  const urlLo = priceMin.trim() ? parsePrice(priceMin) : null;
  const urlHi = priceMax.trim() ? parsePrice(priceMax) : null;
  const lo =
    urlLo != null
      ? clamp(urlLo, fromFilters[0], fromFilters[1])
      : priceMax.trim() && !priceMin.trim()
        ? fromFilters[0]
        : clamp(prev[0], fromFilters[0], fromFilters[1]);
  const hi =
    urlHi != null
      ? clamp(urlHi, fromFilters[0], fromFilters[1])
      : priceMin.trim() && !priceMax.trim()
        ? fromFilters[1]
        : clamp(prev[1], fromFilters[0], fromFilters[1]);
  if (lo <= hi) return [lo, hi];
  const prevLo = clamp(prev[0], fromFilters[0], fromFilters[1]);
  const prevHi = clamp(prev[1], fromFilters[0], fromFilters[1]);
  if (prevLo <= prevHi) return [prevLo, prevHi];
  return fromFilters;
}

/** Pair thumb release value with the other thumb from the in-drag range snapshot. */
export function resolveCatalogPriceThumbCommit(
  thumb: RangeThumb,
  thumbValue: number,
  dragRange: [number, number],
): [number, number] {
  const [lo, hi] = dragRange;
  return thumb === "lo" ? [thumbValue, hi] : [lo, thumbValue];
}

/** Map committed thumb positions to URL price params. */
export function resolveCatalogPriceRangeCommit(
  lo: number,
  hi: number,
  bounds: { minBound: number; maxBound: number },
  priceMin = "",
  priceMax = "",
): { priceMin: string; priceMax: string } {
  const hasMin = priceMin.trim().length > 0;
  const hasMax = priceMax.trim().length > 0;
  const atMin = lo <= bounds.minBound;
  const atMax = hi >= bounds.maxBound;

  if (atMin && atMax) {
    if (!hasMin && !hasMax) {
      return { priceMin: "", priceMax: "" };
    }
    return {
      priceMin: lo > bounds.minBound ? String(lo) : hasMin ? String(bounds.minBound) : "",
      priceMax: hi < bounds.maxBound ? String(hi) : hasMax ? String(bounds.maxBound) : "",
    };
  }

  const nextMin = lo > bounds.minBound ? String(lo) : "";
  let nextMax = "";
  if (hi < bounds.maxBound) {
    nextMax = String(hi);
  } else if (lo > bounds.minBound) {
    nextMax = String(hi);
  }

  return { priceMin: nextMin, priceMax: nextMax };
}

const THUMB_SIZE = 20;
const TRACK_HEIGHT = 4;
const SLIDER_HEIGHT = 40;
const THUMB_OFFSET = -((THUMB_SIZE - TRACK_HEIGHT) / 2);

const rangeInputStyle: CSSProperties = {
  position: "absolute",
  left: 0,
  right: 0,
  top: 0,
  width: "100%",
  height: SLIDER_HEIGHT,
  margin: 0,
  padding: 0,
  background: "transparent",
  appearance: "none",
  WebkitAppearance: "none",
  pointerEvents: "none",
  cursor: "grab",
};

export type CatalogPriceSliderProps = {
  boundsMin?: number | string | null;
  boundsMax?: number | string | null;
  boundsLoading?: boolean;
  priceMin: string;
  priceMax: string;
  onPriceMinChange: (value: string) => void;
  onPriceMaxChange: (value: string) => void;
  onPriceRangeChange?: (priceMin: string, priceMax: string) => void;
  resetToken?: string;
};

export function CatalogPriceSlider({
  boundsMin,
  boundsMax,
  boundsLoading = false,
  priceMin,
  priceMax,
  onPriceMinChange,
  onPriceMaxChange,
  onPriceRangeChange,
  resetToken = "",
}: CatalogPriceSliderProps) {
  const bounds = useMemo(() => resolveBounds(boundsMin, boundsMax), [boundsMin, boundsMax]);

  const fullRange = useCallback((): [number, number] => {
    if (!bounds) return [0, 100_000];
    return [bounds.minBound, bounds.maxBound];
  }, [bounds]);

  const rangeFromFilters = useCallback((): [number, number] => {
    if (!bounds) return fullRange();
    const lo = priceMin.trim() ? (parsePrice(priceMin) ?? bounds.minBound) : bounds.minBound;
    const hi = priceMax.trim() ? (parsePrice(priceMax) ?? bounds.maxBound) : bounds.maxBound;
    return [
      clamp(lo, bounds.minBound, bounds.maxBound),
      clamp(hi, bounds.minBound, bounds.maxBound),
    ];
  }, [priceMin, priceMax, bounds, fullRange]);

  const [range, setRange] = useState<[number, number]>([0, 100_000]);
  const dragRangeRef = useRef(range);
  dragRangeRef.current = range;
  const isDraggingRef = useRef(false);
  const lastBoundsKey = useRef("");
  const skipNextSyncRef = useRef(false);
  const lastCommitAtRef = useRef(0);

  const boundsKey = bounds ? `${bounds.minBound}:${bounds.maxBound}` : "";

  const syncRangeFromFilters = useCallback(
    (prev: [number, number]) =>
      mergeCatalogPriceSliderRange(prev, rangeFromFilters(), priceMin, priceMax),
    [priceMin, priceMax, rangeFromFilters],
  );

  useEffect(() => {
    if (!bounds || !boundsKey) return;
    if (lastBoundsKey.current !== boundsKey) {
      lastBoundsKey.current = boundsKey;
      if (skipNextSyncRef.current) {
        skipNextSyncRef.current = false;
        return;
      }
      setRange((prev) => syncRangeFromFilters(prev));
    }
  }, [boundsKey, bounds, syncRangeFromFilters]);

  useEffect(() => {
    if (isDraggingRef.current || !bounds) return;
    if (skipNextSyncRef.current) {
      skipNextSyncRef.current = false;
      return;
    }
    setRange((prev) => syncRangeFromFilters(prev));
  }, [resetToken, syncRangeFromFilters, bounds]);

  const applyRange = useCallback(
    (lo: number, hi: number) => {
      if (!bounds) return;
      const next = resolveCatalogPriceRangeCommit(lo, hi, bounds, priceMin, priceMax);
      if (onPriceRangeChange) {
        onPriceRangeChange(next.priceMin, next.priceMax);
        return;
      }
      onPriceMinChange(next.priceMin);
      onPriceMaxChange(next.priceMax);
    },
    [bounds, onPriceMinChange, onPriceMaxChange, onPriceRangeChange, priceMin, priceMax],
  );

  const commitRange = useCallback(
    (lo: number, hi: number) => {
      if (!bounds) return;
      const nextLo = clamp(Math.min(lo, hi), bounds.minBound, bounds.maxBound);
      const nextHi = clamp(Math.max(lo, hi), bounds.minBound, bounds.maxBound);
      const next: [number, number] = [nextLo, nextHi];
      dragRangeRef.current = next;
      setRange(next);
      skipNextSyncRef.current = true;
      isDraggingRef.current = false;
      applyRange(nextLo, nextHi);
    },
    [applyRange, bounds],
  );

  const commitThumbRange = useCallback(
    (thumb: RangeThumb, thumbValue: number) => {
      const now = Date.now();
      if (now - lastCommitAtRef.current < 50) return;
      lastCommitAtRef.current = now;
      const [lo, hi] = resolveCatalogPriceThumbCommit(thumb, thumbValue, dragRangeRef.current);
      commitRange(lo, hi);
    },
    [commitRange],
  );

  const handleThumbPointerUp = useCallback(
    (event: PointerEvent<HTMLInputElement>, thumb: RangeThumb) => {
      commitThumbRange(thumb, Number(event.currentTarget.value));
    },
    [commitThumbRange],
  );

  const handleThumbTouchEnd = useCallback(
    (event: TouchEvent<HTMLInputElement>, thumb: RangeThumb) => {
      commitThumbRange(thumb, Number(event.currentTarget.value));
    },
    [commitThumbRange],
  );

  if (!bounds) {
    return (
      <div className="pb-5 mb-5 border-b border-sp-border">
        <div className="text-[11px] uppercase tracking-[0.1em] font-semibold text-sp-text-muted mb-4">
          Цена {boundsLoading ? "…" : ""}
        </div>
      </div>
    );
  }

  const [lo, hi] = range;
  const span = Math.max(1, bounds.maxBound - bounds.minBound);
  const loPct = ((clamp(lo, bounds.minBound, bounds.maxBound) - bounds.minBound) / span) * 100;
  const hiPct = ((clamp(hi, bounds.minBound, bounds.maxBound) - bounds.minBound) / span) * 100;
  const disabled = bounds.maxBound <= bounds.minBound;
  const isFiltered = isCatalogPriceSliderFiltered(lo, hi, bounds, priceMin, priceMax);
  const fillWidth = Math.max(0, hiPct - loPct);
  const trackStyle: CSSProperties = {
    top: "50%",
    transform: "translateY(-50%)",
    height: TRACK_HEIGHT,
  };

  return (
    <div className="mb-5 border-b border-sp-border pb-5">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-sp-text-muted">
        Цена
      </div>

      <div
        className="catalog-price-range-native relative mb-4"
        style={{ height: SLIDER_HEIGHT, touchAction: "none" }}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 rounded-full bg-sp-border"
          style={trackStyle}
        />
        {isFiltered && fillWidth > 0 ? (
          <div
            aria-hidden
            className="pointer-events-none absolute rounded-full"
            style={{
              ...trackStyle,
              left: `${loPct}%`,
              width: `${fillWidth}%`,
              transform: "translateY(-50%)",
              background: "linear-gradient(to right, var(--sp-cyan), var(--sp-blue))",
            }}
          />
        ) : null}
        <input
          type="range"
          min={bounds.minBound}
          max={bounds.maxBound}
          step={1}
          value={lo}
          disabled={disabled}
          aria-label="Цена от"
          style={{ ...rangeInputStyle, zIndex: 5 }}
          onPointerDown={() => {
            isDraggingRef.current = true;
          }}
          onChange={(e) => {
            isDraggingRef.current = true;
            const nextLo = Number(e.target.value);
            setRange(([_, currentHi]) => {
              const loVal = clamp(nextLo, bounds.minBound, currentHi);
              const next: [number, number] = [loVal, currentHi];
              dragRangeRef.current = next;
              return next;
            });
          }}
          onPointerUp={(event) => handleThumbPointerUp(event, "lo")}
          onTouchEnd={(event) => handleThumbTouchEnd(event, "lo")}
        />
        <input
          type="range"
          min={bounds.minBound}
          max={bounds.maxBound}
          step={1}
          value={hi}
          disabled={disabled}
          aria-label="Цена до"
          style={{ ...rangeInputStyle, zIndex: 4 }}
          onPointerDown={() => {
            isDraggingRef.current = true;
          }}
          onChange={(e) => {
            isDraggingRef.current = true;
            const nextHi = Number(e.target.value);
            setRange(([currentLo]) => {
              const hiVal = clamp(nextHi, currentLo, bounds.maxBound);
              const next: [number, number] = [currentLo, hiVal];
              dragRangeRef.current = next;
              return next;
            });
          }}
          onPointerUp={(event) => handleThumbPointerUp(event, "hi")}
          onTouchEnd={(event) => handleThumbTouchEnd(event, "hi")}
        />
      </div>

      <div className="flex items-center justify-between text-[14px] text-sp-text-secondary">
        <span>{formatRub(lo)}</span>
        <span>{formatRub(hi)}</span>
      </div>

      <style>{`
        .catalog-price-range-native input[type="range"] {
          pointer-events: none;
          accent-color: transparent;
          background: transparent;
        }
        .catalog-price-range-native input[type="range"]::-webkit-slider-thumb {
          pointer-events: auto;
        }
        .catalog-price-range-native input[type="range"]::-moz-range-thumb {
          pointer-events: auto;
        }
        .catalog-price-range-native input[type="range"]::-webkit-slider-runnable-track {
          -webkit-appearance: none;
          appearance: none;
          height: ${TRACK_HEIGHT}px;
          background: transparent;
          border: none;
          border-radius: 999px;
        }
        .catalog-price-range-native input[type="range"]::-moz-range-track {
          height: ${TRACK_HEIGHT}px;
          background: transparent;
          border: none;
          border-radius: 999px;
        }
        .catalog-price-range-native input[type="range"]::-moz-range-progress {
          background: transparent;
        }
        .catalog-price-range-native input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: ${THUMB_SIZE}px;
          height: ${THUMB_SIZE}px;
          margin-top: ${THUMB_OFFSET}px;
          border-radius: 50%;
          background: #ffffff;
          border: 2px solid var(--sp-blue);
          box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
          cursor: grab;
        }
        .catalog-price-range-native input[type="range"]::-moz-range-thumb {
          width: ${THUMB_SIZE}px;
          height: ${THUMB_SIZE}px;
          border-radius: 50%;
          background: #ffffff;
          border: 2px solid var(--sp-blue);
          box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
          cursor: grab;
        }
      `}</style>
    </div>
  );
}
