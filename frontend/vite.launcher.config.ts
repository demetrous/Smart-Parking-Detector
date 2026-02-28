import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
import { fileURLToPath } from 'url'
import { createRequire } from 'module'
import path from 'path'

// This config lives in %LOCALAPPDATA%\ParkingSpotter\frontend\ (local NTFS),
// next to node_modules.  Setting `root` to the source tree on the cloud drive
// makes Vite resolve index.html, src/, and env files from there, while
// node_modules are resolved locally (no cloud-sync conflicts).
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const localModules = path.join(__dirname, 'node_modules')

// createRequire scoped to this file so bare imports resolve from AppData
const _require = createRequire(import.meta.url)

const projectRoot = process.env.VITE_PROJECT_ROOT
if (!projectRoot) {
  throw new Error('VITE_PROJECT_ROOT is not set -- start via dev.ps1')
}

/**
 * Resolve bare module imports from the local AppData node_modules.
 *
 * Vite's import-analysis plugin walks up from each source file to find
 * node_modules.  Walking up from a Google Drive path never reaches AppData,
 * so bare imports fail.  This plugin intercepts them first.
 */
const localResolver = {
  name: 'local-modules-resolver',
  resolveId(id: string) {
    if (
      id.startsWith('.') ||
      id.startsWith('/') ||
      path.isAbsolute(id) ||
      id.startsWith('\0') ||
      id.startsWith('node:') ||
      id === 'vite'
    ) return null
    try {
      return _require.resolve(id)
    } catch {
      return null
    }
  },
}

export default defineConfig({
  root: projectRoot,
  plugins: [localResolver, react(), tailwind()],
  resolve: {
    modules: [localModules, 'node_modules'],
  },
  optimizeDeps: {
    // esbuild (pre-bundler) has its own resolver; nodePaths tells it to look
    // in the local AppData modules so transitive deps are found correctly.
    esbuildOptions: {
      nodePaths: [localModules],
    },
  },
  server: {
    fs: { allow: [projectRoot, localModules] },
  },
})
