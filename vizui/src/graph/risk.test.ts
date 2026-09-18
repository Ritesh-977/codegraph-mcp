import { describe, expect, it } from 'vitest'
import { RISK_RAMP, riskScore, riskStep } from './risk'

describe('risk encoding', () => {
  it('is the product, so a busy leaf loses to a busy hub', () => {
    expect(riskScore({ commits: 22, fan_in: 21 })!).toBeGreaterThan(
      riskScore({ commits: 40, fan_in: 1 })!,
    )
  })

  it('treats missing git history as no risk rather than zero churn', () => {
    expect(riskScore({ commits: null, fan_in: 20 })).toBeNull()
  })

  it('is a sequential ramp: monotonically lighter with magnitude', () => {
    // On a dark surface a sequential ramp runs surface-ward -> bright, so
    // luminance must increase step by step and never double back.
    const lum = RISK_RAMP.map((hex) => {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      return 0.2126 * r + 0.7152 * g + 0.0722 * b
    })
    for (let i = 1; i < lum.length; i++) expect(lum[i]).toBeGreaterThan(lum[i - 1])
  })

  it('buckets by share of the maximum, and clamps', () => {
    expect(riskStep(0, 100)).toBe(0)
    expect(riskStep(100, 100)).toBe(RISK_RAMP.length - 1)
    expect(riskStep(500, 100)).toBe(RISK_RAMP.length - 1)
  })

  it('does not divide by zero when nothing has any risk', () => {
    expect(riskStep(0, 0)).toBe(0)
  })
})
