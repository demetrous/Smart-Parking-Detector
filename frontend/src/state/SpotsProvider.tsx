import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Spot } from '../types';
import { connectWs, fetchSpots } from '../lib/api';
import type { WsController } from '../lib/api';

type Ctx = {
  spots: Spot[];
  byId: Map<string, Spot>;
  recentlyHidden: Set<string>; // pins temporarily hidden after turning occupied
  connected: boolean;
};

const SpotsCtx = createContext<Ctx>({
  spots: [],
  byId: new Map(),
  recentlyHidden: new Set(),
  connected: false,
});

export function SpotsProvider({ children }: { children: ReactNode }) {
  const [spots, setSpots] = useState<Spot[]>([]);
  const [recentlyHidden, setRecentlyHidden] = useState<Set<string>>(new Set());
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ctrl: WsController | null = null;
    let cancelled = false;

    (async () => {
      try {
        const initial = await fetchSpots();
        if (cancelled) return;
        setSpots(initial);
        // Hide initially occupied pins until they change
        setRecentlyHidden(new Set(initial.filter(s => s.status === 'occupied').map(s => s.id)));
      } catch {
        // ignore — backend may not be running yet
      }

      if (cancelled) return;

      ctrl = connectWs(
        (ev) => {
          setSpots((prev) => {
            const idx = prev.findIndex((s) => s.id === ev.payload.id);
            const updated = ev.payload;
            const next =
              idx === -1
                ? [updated, ...prev]
                : (() => {
                    const copy = prev.slice();
                    copy[idx] = updated;
                    return copy;
                  })();
            // If became occupied, hide pin after 3 s
            if (updated.status === 'occupied') {
              setTimeout(() => {
                setRecentlyHidden((old) => new Set(old).add(updated.id));
              }, 3000);
            } else {
              setRecentlyHidden((old) => {
                const n = new Set(old);
                n.delete(updated.id);
                return n;
              });
            }
            return next;
          });
        },
        (status) => setConnected(status === 'connected'),
      );
    })();

    return () => {
      cancelled = true;
      ctrl?.close();
    };
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      spots,
      byId: new Map(spots.map((s) => [s.id, s])),
      recentlyHidden,
      connected,
    }),
    [spots, recentlyHidden, connected],
  );

  return <SpotsCtx.Provider value={value}>{children}</SpotsCtx.Provider>;
}

export function useSpots() {
  return useContext(SpotsCtx);
}
