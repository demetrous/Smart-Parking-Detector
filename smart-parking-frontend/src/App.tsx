import { ThemeProvider, useTheme } from './components/ThemeProvider';
import ParkingMap from './components/ParkingMap';

function Toolbar() {
  const { theme, toggle } = useTheme();
  return (
    <div className="fixed top-2 left-2 z-50 rounded-xl bg-white/80 dark:bg-slate-900/80 backdrop-blur border border-slate-200 dark:border-slate-700 p-2 flex gap-2">
      <button
        className="px-3 py-1 rounded-md bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900"
        onClick={toggle}
        aria-label="Toggle theme"
      >
        {theme === 'dark' ? 'Light' : 'Dark'}
      </button>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <main className="h-dvh w-full">
        <ParkingMap />
        <Toolbar />
        <div className="fixed inset-x-0 bottom-0 md:bottom-4 md:left-4 md:w-96 md:rounded-xl bg-white/90 dark:bg-slate-900/90 backdrop-blur border border-slate-200 dark:border-slate-700 p-3 text-sm">
          <div className="flex items-center gap-3">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500" aria-hidden /> Available
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500 ml-3" aria-hidden /> Soon
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-rose-500 ml-3" aria-hidden /> Occupied
          </div>
        </div>
      </main>
    </ThemeProvider>
  );
}
