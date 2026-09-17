import type { ReactNode } from 'react'

const KEYWORDS = new Set([
  'import', 'from', 'def', 'class', 'return', 'if', 'elif', 'else', 'for', 'while',
  'func', 'const', 'let', 'var', 'function', 'export', 'async', 'await', 'type',
  'interface', 'package', 'public', 'private', 'static', 'void', 'int', 'str',
])

// Deliberately crude: one regex pass, no per-language grammar. The detail
// panel shows source for orientation, not for editing.
export function highlightLine(line: string): ReactNode[] {
  const parts: ReactNode[] = []
  const re = /(\/\/.*$|#.*$|'[^']*'|"[^"]*"|`[^`]*`|\b[A-Za-z_][A-Za-z0-9_]*\b)/g
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  while ((m = re.exec(line)) !== null) {
    if (m.index > last) parts.push(line.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('//') || tok.startsWith('#')) {
      parts.push(<span key={k++} style={{ color: '#6a9955' }}>{tok}</span>)
    } else if (tok.startsWith("'") || tok.startsWith('"') || tok.startsWith('`')) {
      parts.push(<span key={k++} style={{ color: '#ce9178' }}>{tok}</span>)
    } else if (KEYWORDS.has(tok)) {
      parts.push(<span key={k++} style={{ color: '#569cd6' }}>{tok}</span>)
    } else {
      parts.push(tok)
    }
    last = m.index + tok.length
  }
  if (last < line.length) parts.push(line.slice(last))
  return parts
}
