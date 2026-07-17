function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function safeHref(value: string): string {
  const trimmed = value.trim()
  if (/\s|&(?:quot|#39|lt|gt);/i.test(trimmed)) return '#'
  return /^(https?:\/\/|\/(?!\/)|#)/i.test(trimmed) ? trimmed : '#'
}

function renderInline(value: string): string {
  return value
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)]\(([^)]+)\)/g, (_match, label: string, href: string) => (
      `<a href="${safeHref(href)}" target="_blank" rel="noopener noreferrer">${label}</a>`
    ))
}

export function renderSafeMarkdown(source: string): string {
  const lines = escapeHtml(source).replaceAll('\r\n', '\n').split('\n')
  const output: string[] = []
  let inCodeBlock = false
  let inList = false

  for (const line of lines) {
    if (line.startsWith('```')) {
      if (inList) {
        output.push('</ul>')
        inList = false
      }
      if (inCodeBlock) {
        output.push('</code></pre>')
        inCodeBlock = false
      } else {
        const language = line.slice(3).trim().replace(/[^a-z0-9_-]/gi, '')
        output.push(`<pre><code${language ? ` class="language-${language}"` : ''}>`)
        inCodeBlock = true
      }
      continue
    }

    if (inCodeBlock) {
      output.push(`${line}\n`)
      continue
    }

    const listMatch = line.match(/^[-*] (.+)$/)
    if (listMatch) {
      if (!inList) {
        output.push('<ul>')
        inList = true
      }
      output.push(`<li>${renderInline(listMatch[1])}</li>`)
      continue
    }

    if (inList) {
      output.push('</ul>')
      inList = false
    }

    if (!line.trim()) continue
    if (line.startsWith('### ')) output.push(`<h3>${renderInline(line.slice(4))}</h3>`)
    else if (line.startsWith('## ')) output.push(`<h2>${renderInline(line.slice(3))}</h2>`)
    else if (line.startsWith('# ')) output.push(`<h1>${renderInline(line.slice(2))}</h1>`)
    else if (line.startsWith('> ')) output.push(`<blockquote>${renderInline(line.slice(2))}</blockquote>`)
    else output.push(`<p>${renderInline(line)}</p>`)
  }

  if (inList) output.push('</ul>')
  if (inCodeBlock) output.push('</code></pre>')
  return output.join('')
}
