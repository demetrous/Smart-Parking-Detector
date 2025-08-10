import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { Spot } from '../types';
import { connectWs, fetchSpots } from '../lib/api';

type Ctx = {
  spots: Spot[];
  byId: Map<string, Spot>;
  recentlyHidden: Set<string>; // pins temporarily hidden after turning occupied
};

const SpotsCtx = createContext<Ctx>({ spots: [], byId: new Map(), recentlyHidden: new Set() });

export function SpotsProvider({ children }: { children: React.ReactNode }) {
  const [spots, setSpots] = useState<Spot[]>([]);
  const [recentlyHidden, setRecentlyHidden] = useState<Set<string>>(new Set());

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    (async () => {
      try {
        const initial = await fetchSpots();
        if (closed) return;
        setSpots(initial);
        // Hide initially occupied pins until they change
        setRecentlyHidden(new Set(initial.filter(s => s.status === 'occupied').map(s => s.id)));
      } catch (e) {
        // ignore for now
      }
      ws = connectWs((ev) => {
        setSpots((prev) => {
          const idx = prev.findIndex((s) => s.id === ev.payload.id);
          const updated = ev.payload;
          const next = idx === -1 ? [updated, ...prev] : (() => { const copy = prev.slice(); copy[idx] = updated; return copy; })();
          // If became occupied, hide after 3s
          if (updated.status === 'occupied') {
            setTimeout(() => {
              setRecentlyHidden((old) => new Set(old).add(updated.id));
            }, 3000);
          } else {
            // If available/soon, ensure it's visible again
            setRecentlyHidden((old) => { const n = new Set(old); n.delete(updated.id); return n; });
          }
          return next;
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
    recentlyHidden,
  }), [spots, recentlyHidden]);

  return <SpotsCtx.Provider value={value}>{children}</SpotsCtx.Provider>;
}

export function useSpots() {
  return useContext(SpotsCtx);
}


