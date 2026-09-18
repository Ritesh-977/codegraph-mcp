import { useEffect, useRef } from 'react'
import type { Core } from 'cytoscape'

export function Minimap({ cy }: { cy: Core | null }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (!cy || !ref.current) return
    const cv = ref.current
    let queued = 0
    const draw = (): void => {
      const ctx = cv.getContext('2d')
      if (!ctx) return
      const bb = cy.elements().boundingBox()
      ctx.clearRect(0, 0, cv.width, cv.height)
      if (bb.w === 0 || bb.h === 0) return
      const s = Math.min(cv.width / bb.w, cv.height / bb.h)
      cy.nodes().forEach((n) => {
        const p = n.position()
        ctx.fillStyle = n.data('color') as string
        ctx.fillRect((p.x - bb.x1) * s, (p.y - bb.y1) * s, 2.4, 2.4)
      })
    }
    // `render` fires every frame; redrawing thousands of dots per frame is
    // what makes a minimap a performance bug, so coalesce into one rAF.
    const schedule = (): void => {
      if (queued) return
      queued = requestAnimationFrame(() => {
        queued = 0
        draw()
      })
    }
    cy.on('render', schedule)
    schedule()
    return () => {
      cy.off('render', schedule)
      cancelAnimationFrame(queued)
    }
  }, [cy])

  return (
    <canvas
      ref={ref}
      id="minimap"
      width={180}
      height={120}
      style={{
        position: 'absolute',
        right: 8,
        bottom: 8,
        width: 180,
        height: 120,
        border: '1px solid #39424f',
        background: '#101418',
        zIndex: 10,
        borderRadius: 6,
      }}
    />
  )
}
