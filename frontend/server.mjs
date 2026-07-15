import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const host = '0.0.0.0'
const port = 8080
const root = resolve(fileURLToPath(new URL('./dist/', import.meta.url)))
const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
}

async function findAsset(pathname) {
  const candidate = resolve(root, `.${decodeURIComponent(pathname)}`)
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
    return undefined
  }

  try {
    if ((await stat(candidate)).isFile()) {
      return candidate
    }
  } catch {
    // Unknown routes are handled by the SPA entry point.
  }
  return resolve(root, 'index.html')
}

createServer(async (request, response) => {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    response.writeHead(405, { Allow: 'GET, HEAD' }).end()
    return
  }

  const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`)
  if (url.pathname === '/healthz') {
    response.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' })
    response.end(request.method === 'HEAD' ? undefined : 'ok\n')
    return
  }

  const asset = await findAsset(url.pathname)
  if (!asset) {
    response.writeHead(403).end()
    return
  }

  response.writeHead(200, {
    'Cache-Control': extname(asset) === '.html' ? 'no-cache' : 'public, max-age=31536000, immutable',
    'Content-Type': contentTypes[extname(asset)] ?? 'application/octet-stream',
  })
  if (request.method === 'HEAD') {
    response.end()
    return
  }
  createReadStream(asset).pipe(response)
}).listen(port, host, () => {
  console.log(`Frontend listening on http://${host}:${port}`)
})
