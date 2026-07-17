import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const styles = readFileSync(resolve(process.cwd(), 'src/style.css'), 'utf8')

function mediaBlock(query: string): string {
  const start = styles.indexOf(`@media (${query})`)
  if (start < 0) return ''
  const openingBrace = styles.indexOf('{', start)
  let depth = 0
  for (let index = openingBrace; index < styles.length; index += 1) {
    if (styles[index] === '{') depth += 1
    if (styles[index] === '}') depth -= 1
    if (depth === 0) return styles.slice(openingBrace + 1, index)
  }
  return ''
}

describe('responsive layout contract', () => {
  it('uses a two-column login layout at desktop width', () => {
    expect(styles).toMatch(/\.auth-page\s*{[^}]*grid-template-columns:\s*minmax\(0, 1\.2fr\) minmax\(320px, 440px\)/s)
    expect(styles).toMatch(/body\s*{[^}]*min-width:\s*320px/s)
  })

  it('collapses the login layout at tablet and mobile widths', () => {
    const tablet = mediaBlock('max-width: 760px')

    expect(tablet).toMatch(/\.auth-page\s*{[^}]*grid-template-columns:\s*1fr/s)
    expect(tablet).toMatch(/\.home-page\s*{[^}]*padding-top:\s*64px/s)
  })

  it('keeps primary content and navigation within narrow phone widths', () => {
    const phone = mediaBlock('max-width: 480px')

    expect(phone).toMatch(/\.auth-page\s*{[^}]*width:\s*calc\(100% - 24px\)/s)
    expect(phone).toMatch(/\.home-page\s*{[^}]*width:\s*calc\(100% - 24px\)/s)
    expect(phone).toMatch(/\.status-card\s*{[^}]*width:\s*100%/s)
    expect(phone).toMatch(/nav\s*{[^}]*flex-direction:\s*column/s)
  })
})
