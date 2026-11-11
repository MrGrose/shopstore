import { defineConfig, loadEnv } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

/** SPA-страницы отдаёт Vite; API под тем же префиксом — проксируем на бэкенд. */
function proxySpaPages(backendTarget: string) {
  const bypass = (req: { headers: { accept?: string }; url?: string }) => {
    const accept = req.headers.accept ?? ''
    if (accept.includes('text/html')) {
      return req.url
    }
  }
  return { target: backendTarget, bypass }
}

function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id: string) {
      if (id.startsWith('figma:asset/')) {
        const filename = id.replace('figma:asset/', '')
        return path.resolve(__dirname, 'src/assets', filename)
      }
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget =
    env.VITE_BACKEND_TARGET ?? 'http://localhost:8000'

  return {
    plugins: [
      figmaAssetResolver(),
      react(),
      tailwindcss(),
      {
        name: 'inject-api-preconnect',
        transformIndexHtml(html) {
          const origin = env.VITE_API_ORIGIN?.trim()
          if (!origin) return html
          return html.replace(
            '</head>',
            `  <link rel="preconnect" href="${origin}" crossorigin />\n</head>`,
          )
        },
      },
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      chunkSizeWarningLimit: 700,
    },
    server: {
      proxy: {
        '/products': backendTarget,
        '/product': backendTarget,
        '/cart': proxySpaPages(backendTarget),
        '/orders': proxySpaPages(backendTarget),
        '/catalog': proxySpaPages(backendTarget),
        '/app': proxySpaPages(backendTarget),
        '/checkout': proxySpaPages(backendTarget),
        '/login': proxySpaPages(backendTarget),
        '/auth': backendTarget,
        '/users': backendTarget,
        '/privacy': backendTarget,
        '/terms': backendTarget,
        '/returns': backendTarget,
        '/consent': backendTarget,
        '/storefront': backendTarget,
        '/health': backendTarget,
        '/ready': backendTarget,
        '/media': backendTarget,
        '/static': backendTarget,
        '/internal': backendTarget,
        '/admin': backendTarget,
      },
    },
    assetsInclude: ['**/*.svg', '**/*.csv'],
  }
})
