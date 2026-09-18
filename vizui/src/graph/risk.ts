/**
 * Risk = churn x dependents.
 *
 * Neither number alone finds the file you should be careful with: a file that
 * changes constantly but nothing imports is cheap to get wrong, and a
 * heavily-depended-upon file nobody touches is stable. In the repo this was
 * built against the product separates them cleanly — the top file scores four
 * times the next one, and the ranking is visibly different from fan-in alone.
 */
export function riskScore(n: { commits: number | null; fan_in: number | null }): number | null {
  // No clone, no history: absent, not zero. Painting every node "safe" because
  // we could not read git would be a lie.
  if (n.commits === null) return null
  return n.commits * Math.max(0, n.fan_in ?? 0)
}

/**
 * Sequential ramp — one hue, recessive to bright. On a dark surface the low end
 * sits near the neutral node colour so untouched files recede, and magnitude
 * reads as "glows hotter". Five discrete steps so the legend can show them.
 */
export const RISK_RAMP = ['#4a4550', '#6d4a52', '#96484d', '#c04a45', '#e8736b'] as const

export function riskStep(score: number, max: number): number {
  if (max <= 0) return 0
  const share = Math.min(1, Math.max(0, score / max))
  return Math.min(RISK_RAMP.length - 1, Math.round(share * (RISK_RAMP.length - 1)))
}

export function riskColor(score: number, max: number): string {
  return RISK_RAMP[riskStep(score, max)]
}
