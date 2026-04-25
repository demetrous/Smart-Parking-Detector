import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import tailwind from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin, type PluginOption } from 'vite'

// When the project lives on a cloud-synced drive (e.g. Google Drive) that
// doesn't support npm's parallel file writes, node_modules is stored locally
// at %LOCALAPPDATA%\ParkingSpotter\frontend\node_modules and pointed to via
// LOCAL_MODULES_PATH (set by dev.ps1). Vite 7 has no webpack-style
// resolve.modules; we pre-resolve bare imports with Node from that tree.

function extraNodeModulesResolve(roots: string[]): Plugin {
  const markers = roots
    .map((r) => path.join(r, 'vite', 'package.json'))
    .filter((p) => fs.existsSync(p))
  if (markers.length === 0) {
    return { name: 'extra-node-modules-skipped', resolveId: () => null }
  }
  const projectRequire = createRequire(path.resolve('package.json'))
  const requires = markers.map((m) => createRequire(m))
  return {
    name: 'extra-node-modules',
    enforce: 'pre',
    resolveId(id) {
      if (
        id.startsWith('\0')
        || id.startsWith('.')
        || id.startsWith('/')
        || path.isAbsolute(id)
      ) {
        return null
      }
      try {
        projectRequire.resolve(id)
        return null
      } catch {
        /* use fallback roots below */
      }
      for (const req of requires) {
        try {
          return req.resolve(id)
        } catch {
          /* try next root */
        }
      }
      return null
    },
  }
}

const localModulesEnv = process.env.LOCAL_MODULES_PATH
const defaultLocalModules = path.join(
  os.homedir(),
  'AppData',
  'Local',
  'ParkingSpotter',
  'frontend',
  'node_modules',
)

const extraModules: string[] = []
if (localModulesEnv && fs.existsSync(localModulesEnv)) {
  extraModules.push(path.resolve(localModulesEnv))
} else if (process.platform === 'win32') {
  const abs = path.resolve(defaultLocalModules)
  if (fs.existsSync(abs) && abs !== path.resolve('node_modules')) {
    extraModules.push(abs)
  }
}

function asPlugins(...opts: PluginOption[]): Plugin[] {
  const out: Plugin[] = []
  for (const o of opts) {
    if (o == null || o === false) continue
    if (Array.isArray(o)) out.push(...asPlugins(...o))
    else out.push(o as Plugin)
  }
  return out
}

export default defineConfig({
  plugins: asPlugins(
    ...(extraModules.length > 0 ? [extraNodeModulesResolve(extraModules)] : []),
    react(),
    tailwind(),
  ),
})
