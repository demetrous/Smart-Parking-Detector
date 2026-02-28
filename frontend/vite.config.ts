import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
import path from 'path'
import os from 'os'

// When the project lives on a cloud-synced drive (e.g. Google Drive) that
// doesn't support npm's parallel file writes, node_modules is stored locally
// at %LOCALAPPDATA%\ParkingSpotter\frontend\node_modules and pointed to via
// the LOCAL_MODULES_PATH environment variable (set by dev.ps1).
//
// Falls back to the standard relative node_modules so this config also works
// on a regular local filesystem.
const localModulesEnv = process.env.LOCAL_MODULES_PATH
const defaultLocalModules = path.join(
  os.homedir(),
  'AppData',
  'Local',
  'ParkingSpotter',
  'frontend',
  'node_modules',
)
const extraModules: string[] = localModulesEnv
  ? [localModulesEnv]
  : path.isAbsolute(defaultLocalModules) && defaultLocalModules !== path.resolve('node_modules')
    ? [defaultLocalModules]
    : []

export default defineConfig({
  plugins: [react(), tailwind()],
  resolve: {
    modules: [...extraModules, 'node_modules'],
  },
})
