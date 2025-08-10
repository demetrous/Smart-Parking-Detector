import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { Spot } from '../types';
import { connectWs, fetchSpots } from '../lib/api';

type Ctx = {
  spots: Spot[];
  byId: Map<string, Spot>;
};

const SpotsCtx = createContext<Ctx>({ spots: [], byId: new Map() });

export function SpotsProvider({ children }: { children: React.ReactNode }) {
  const [spots, setSpots] = useState<Spot[]>([]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    (async () => {
      try {
        const initial = await fetchSpots();
        if (closed) return;
        setSpots(initial);
      } catch (e) {
        // ignore for now
      }
      ws = connectWs((ev) => {
        setSpots((prev) => {
          const idx = prev.findIndex((s) => s.id === ev.payload.id);
          if (idx === -1) return [ev.payload, ...prev];
          const copy = prev.slice();
          copy[idx] = ev.payload;
          return copy;
        });
      });
    })();
    return () => {
      closed = true;
      ws?.close();
    };
  }, []);

  const value = useMemo<Ctx>(() => ({
    spots,
    byId: new Map(spots.map((s) => [s.id, s])),
  }), [spots]);

  return <SpotsCtx.Provider value={value}>{children}</SpotsCtx.Provider>;
}

export function useSpots() {
  return useContext(SpotsCtx);
}


