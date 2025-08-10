import { ThemeProvider, useTheme } from './components/ThemeProvider';
import ParkingMap from './components/ParkingMap';
import { SunIcon, MoonIcon } from '@heroicons/react/24/solid';
import clsx from 'clsx';

function Toolbar() {
  const { theme, toggle } = useTheme();
  const isDark = theme === 'dark';
  const wrapClass = clsx(
    'fixed top-2 left-2 z-50 p-1 rounded-xl backdrop-blur border transition-colors',
    isDark ? 'bg-slate-900/90 border-slate-700' : 'bg-white/90 border-slate-200'
  );
  const btnClass = clsx(
    'inline-flex items-center justify-center h-10 w-10 rounded-lg border shadow-sm transition-colors',
    isDark
      ? 'bg-slate-800 text-slate-100 border-slate-600 hover:bg-slate-700'
      : 'bg-white text-slate-900 border-slate-300 hover:bg-slate-100'
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
    </div>
  );
}

function Shell() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const legendClass = clsx(
    'fixed inset-x-0 bottom-0 md:bottom-4 md:left-4 md:w-96 md:rounded-xl backdrop-blur p-3 text-sm shadow-lg border transition-colors',
    isDark
      ? 'bg-slate-900/90 text-slate-100 border-slate-700'
      : 'bg-white/95 text-slate-900 border-slate-200'
  );
  return (
    <main className="h-dvh w-full">
      <ParkingMap />
      <Toolbar />
      <div className={legendClass}>
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
