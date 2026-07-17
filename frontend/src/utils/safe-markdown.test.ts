import { describe, expect, it } from 'vitest'

import { renderSafeMarkdown } from './safe-markdown'

describe('renderSafeMarkdown', () => {
  it('renders supported Markdown while escaping raw HTML', () => {
    const html = renderSafeMarkdown('# 推荐\n\n**安静**且有 `插座`\n<script>alert(1)</script>')

    expect(html).toContain('<h1>推荐</h1>')
    expect(html).toContain('<strong>安静</strong>')
    expect(html).toContain('<code>插座</code>')
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<script>')
  })

  it('adds safe external-link attributes and rejects script URLs', () => {
    const html = renderSafeMarkdown(
      '[原始点评](https://example.com/review) [危险](javascript:alert(1)) [注入](https://example.com" onmouseover="alert(1))',
    )

    expect(html).toContain('href="https://example.com/review"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('onmouseover=')
  })
})
