import { ThemeProvider, useTheme } from './components/ThemeProvider';
import ParkingMap from './components/ParkingMap';
import SimulationView from './components/SimulationView';
import { SunIcon, MoonIcon, SignalSlashIcon, CubeTransparentIcon, MapIcon } from '@heroicons/react/24/solid';
import clsx from 'clsx';
import { useState } from 'react';
import { useSpots } from './state/SpotsProvider';

function Toolbar({ view, setView }: { view: 'map' | 'simulation'; setView: (view: 'map' | 'simulation') => void }) {
  const { theme, toggle } = useTheme();
  const { connected } = useSpots();
  const isDark = theme === 'dark';
  const wrapClass = clsx(
    'fixed top-2 left-2 z-50 p-1 rounded-xl backdrop-blur border transition-colors',
    isDark ? 'bg-slate-900/90 border-slate-700' : 'bg-white/90 border-slate-200',
  );
  const btnClass = clsx(
    'inline-flex items-center justify-center h-10 w-10 rounded-lg border shadow-sm transition-colors',
    isDark
      ? 'bg-slate-800 text-slate-100 border-slate-600 hover:bg-slate-700'
      : 'bg-white text-slate-900 border-slate-300 hover:bg-slate-100',
  );
  return (
    <div className={wrapClass}>
      <button
        className={btnClass}
        onClick={toggle}
        aria-label="Toggle color theme"
        title={isDark ? 'Switch to light' : 'Switch to dark'}
      >
        {isDark ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
      </button>
      <button
        className={clsx(btnClass, 'ml-1')}
        onClick={() => setView(view === 'map' ? 'simulation' : 'map')}
        aria-label={view === 'map' ? 'Show synthetic simulation' : 'Show map'}
        title={view === 'map' ? 'Show synthetic simulation' : 'Show map'}
      >
        {view === 'map' ? <CubeTransparentIcon className="h-5 w-5" /> : <MapIcon className="h-5 w-5" />}
      </button>
      {!connected && (
        <div
          className={clsx(
            'mt-1 flex items-center gap-1.5 px-2 py-1 rounded-lg border text-xs font-medium',
            isDark
              ? 'bg-rose-900/80 text-rose-200 border-rose-700'
              : 'bg-rose-50 text-rose-700 border-rose-200',
          )}
          title="WebSocket disconnected — reconnecting…"
          aria-live="polite"
        >
          <SignalSlashIcon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          Offline
        </div>
      )}
    </div>
  );
}

function Shell() {
  const [view, setView] = useState<'map' | 'simulation'>('map');
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const legendClass = clsx(
    'fixed inset-x-0 bottom-0 md:bottom-4 md:left-4 md:w-96 md:rounded-xl backdrop-blur p-3 text-sm shadow-lg border transition-colors',
    isDark
      ? 'bg-slate-900/90 text-slate-100 border-slate-700'
      : 'bg-white/95 text-slate-900 border-slate-200',
  );
  return (
    <main className="h-dvh w-full">
      {view === 'map' ? <ParkingMap /> : <SimulationView />}
      <Toolbar view={view} setView={setView} />
      <div className={clsx(legendClass, view === 'simulation' && 'hidden md:block')}>
        <div className="flex items-center gap-3">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500" aria-hidden /> Available
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500 ml-3" aria-hidden /> Soon
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-rose-500 ml-3" aria-hidden /> Occupied
        </div>
      </div>
    </main>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <Shell />
    </ThemeProvider>
  );
}
