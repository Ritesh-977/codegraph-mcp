import type { Core, NodeSingular } from 'cytoscape'

let raf = 0
let offsets: number[] = []
let active = false

export function startFlow(cy: Core, nodeId: string | null): void {
  const canvas = document.getElementById('flow-canvas') as HTMLCanvasElement | null
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx || !nodeId) {
    stopFlow()
    return
  }
  const ele = cy.$id(nodeId)
  if (ele.empty()) {
    stopFlow()
    return
  }
  // Cytoscape has no `otherNode`; walk the edge's own endpoints instead.
  const neighbours: NodeSingular[] = ele
    .connectedEdges()
    .map((e) => (e.source().id() === ele.id() ? e.target() : e.source()))
    .filter((n) => !n.empty() && n.id() !== ele.id())
  offsets = neighbours.map((_, i) => (i % 12) / 12)
  active = true
  cancelAnimationFrame(raf)
  const tick = (): void => {
    // The canvas is CSS-stretched over the cytoscape viewport but its bitmap
    // defaults to 300x150 — without this sync the particles land in a
    // different coordinate space than the one the user sees.
    if (canvas.width !== canvas.clientWidth) canvas.width = canvas.clientWidth
    if (canvas.height !== canvas.clientHeight) canvas.height = canvas.clientHeight
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    // Positions are re-read every frame so particles track pan and zoom.
    const from = ele.renderedPosition()
    neighbours.forEach((n, i) => {
      const to = n.renderedPosition()
      offsets[i] = (offsets[i] + 0.01) % 1
      const t = offsets[i]
      ctx.beginPath()
      ctx.arc(from.x + (to.x - from.x) * t, from.y + (to.y - from.y) * t, 2.2, 0, Math.PI * 2)
      ctx.fillStyle = '#7fc4ff'
      ctx.fill()
    })
    if (active) raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
}

export function stopFlow(): void {
  active = false
  cancelAnimationFrame(raf)
  const canvas = document.getElementById('flow-canvas') as HTMLCanvasElement | null
  canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
}
