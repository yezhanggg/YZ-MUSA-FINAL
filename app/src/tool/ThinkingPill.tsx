// Thinking Pill by Louis Studios (https://studios.lou15.com/?ref=21st-code), from the 21st.dev catalogue.
// Adapted for this tool: a light frosted glass that fits the white ParcelIQ card, the app's violet, indigo and sky
// colours, and a dark label. ParcelIQ shows it while an answer is on its way (AskBox).

import * as React from "react"

export interface ThinkingPillProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "children"> {
  /** Text shown in the pill and announced to screen readers. */
  label?: string
  /** Show an animated "..." after the label. */
  dots?: boolean
  /** Pill width in px. */
  width?: number
  /** Pill height in px. Defaults to 0.3 × width, the proportion of the original. */
  height?: number
  /** Playback speed. 1 = one full aurora loop every 12 s. */
  speed?: number
  /**
   * Aurora colours from left to right, any CSS colour. Two or more; they are
   * resampled to ten even stops. Defaults to the app's violet, indigo, sky and teal sweep.
   */
  colors?: string[]
  /** When false the aurora fades out and the pill rests as light glass. */
  active?: boolean
  /** A soft light glint sweeping across the label. */
  shimmer?: boolean
}

// Band colours, left to right: Tailwind violet-400 to 600, indigo-500, sky-400 and a hint of teal-400.
const DEFAULT_COLORS = [
  "#a78bfa", "#8b5cf6", "#7c3aed", "#6366f1", "#38bdf8", "#2dd4bf", "#38bdf8", "#6366f1", "#8b5cf6", "#a78bfa",
]

// Everything moves on one seamless loop: every motion below completes a whole
// number of cycles in LOOP seconds, so frame LOOP is frame 0.
const LOOP = 12
const STOPS = 10
// Label size as a fraction of the pill height, matched to the reference.
const FONT = 0.34
const TAU = Math.PI * 2

const VERT = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`

const FRAG = `
precision highp float;
uniform vec2 uRes;
uniform float uPx;    // one CSS pixel in device pixels
uniform float uPh;    // loop phase, 0..2π
uniform float uOn;    // aurora strength, 0..1
uniform vec3 uCol[${STOPS}];

const float TAU = 6.2831853;

vec3 palette(float x) {
  x = clamp(x, 0.0, 1.0) * ${STOPS - 1}.0;
  vec3 c = uCol[0];
  for (int i = 1; i < ${STOPS}; i++) {
    float f = clamp(x - float(i - 1), 0.0, 1.0);
    c = mix(c, uCol[i], f * f * (3.0 - 2.0 * f));
  }
  return c;
}

// Crest of the colour band, 0 = top of the pill, 1 = bottom. The still is a
// Fourier fit to the reference; ripples travel over it in both directions.
float crest(float u, float ph) {
  float e = 0.4873
    + 0.1265 * sin(TAU * 0.6 * u - 2.6533)
    + 0.2222 * sin(TAU * 1.1 * u - 0.4660)
    + 0.1004 * sin(TAU * 1.7 * u + 0.2938)
    + 0.0232 * sin(TAU * 2.4 * u - 2.7535)
    // The fit tracks the fringe; the colour itself starts a touch lower here.
    + 0.040 * exp(-pow((u - 0.14) / 0.075, 2.0))
    + 0.015 * exp(-pow((u - 0.8) / 0.1, 2.0));
  float r = 0.060 * (sin(TAU * 1.15 * u - 3.0 * ph + 0.7) - sin(TAU * 1.15 * u + 0.7))
          + 0.040 * (sin(TAU * 1.9 * u + 4.0 * ph + 1.9) - sin(TAU * 1.9 * u + 1.9))
          + 0.018 * (sin(TAU * 3.1 * u - 6.0 * ph + 2.5) - sin(TAU * 3.1 * u + 2.5))
          + 0.020 * (sin(ph + 0.4) - sin(0.4));
  return e + r;
}

float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

void main() {
  vec2 fc = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
  float H = uRes.y;
  float u = fc.x / uRes.x;
  float y = fc.y / H;
  float ph = uPh;

  // Stadium distance in device px, negative inside.
  float R = 0.5 * H;
  vec2 q = abs(fc - 0.5 * uRes) - vec2(0.5 * uRes.x - R, 0.0);
  float sd = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - R;
  float din = max(-sd, 0.0) / H;

  // Colours slosh gently along the band. In the middle the crest runs blue
  // and the deeper water leans back toward teal and green.
  float e = crest(u, ph);
  float d = y - e;
  float mid = exp(-pow((u - 0.5) / 0.15, 2.0));
  float hx = u + mid * (0.04 - 0.17 * smoothstep(0.0, 0.22, d))
    + 0.070 * (sin(TAU * 0.8 * u - ph + 1.0) - sin(TAU * 0.8 * u + 1.0))
    + 0.035 * (sin(TAU * 1.7 * u + 2.0 * ph + 0.3) - sin(TAU * 1.7 * u + 0.3))
    + 0.030 * (sin(TAU * 1.15 * u - 3.0 * ph + 0.7) - sin(TAU * 1.15 * u + 0.7));
  vec3 c = palette(hx);
  // Light travelling along the band: brighter swells ride the wave sideways.
  // Zero at t = 0, so the still keeps the sampled colours.
  c *= 1.0 + 0.15 * (sin(TAU * 1.4 * u - 3.0 * ph) - sin(TAU * 1.4 * u))
           + 0.07 * (sin(TAU * 2.3 * u + 4.0 * ph + 1.2) - sin(TAU * 2.3 * u + 1.2));

  // Light glass above the band (stone-50), so the pill sits on a white card.
  vec3 ink = vec3(0.980, 0.976, 0.969);
  vec3 col = ink;

  // Above the crest: a thin coloured fringe and a faint bloom, mixed into the
  // light glass. The middle is hazier than the two ends.
  float haze = exp(-pow((u - 0.52) / 0.09, 2.0));
  float up = max(-d, 0.0) / (1.0 + 1.6 * haze);
  col = mix(col, c, uOn * 0.55 * exp(-up / 0.03));
  col = mix(col, c, uOn * (0.10 + 0.06 * haze) * exp(-up / 0.07));

  // Below the crest: the saturated band, melting into milky frosted glass.
  float body = smoothstep(0.004 - 0.034 * haze, 0.045 + 0.04 * haze, d);
  // Frost comes from two sides: depth below the crest, and the milky floor
  // of the glass, which starts at about two thirds of the height.
  float frost = 1.0 - (1.0 - smoothstep(0.03, 0.4, d)) * (1.0 - 0.85 * smoothstep(0.6, 0.76, y));
  float lum = mix(0.84, 0.92, smoothstep(0.65, 0.9, y)) + 0.03 * sin(ph * 2.0 + 0.5) * smoothstep(0.4, 0.9, y);
  vec3 chroma = c / max(dot(c, vec3(0.3333)), 0.06);
  // Cool colours stain the frost more than warm ones, as in the reference.
  float stain = mix(0.24, 0.06, smoothstep(0.72, 0.97, y)) * (1.0 + 0.9 * smoothstep(0.6, 0.95, u));
  vec3 milk = lum * mix(vec3(1.0), chroma, stain);
  vec3 band = mix(c, milk, frost);
  // A second, fainter ribbon of light drifts inside the band on its own
  // current, so the colour reads as layered liquid rather than a flat fill.
  float rib = d - 0.11 - 0.035 * sin(TAU * 1.6 * u + 3.0 * ph + 0.8) - 0.02 * sin(TAU * 2.7 * u - 5.0 * ph);
  band += c * 0.11 * exp(-rib * rib / 0.0025) * (0.6 + 0.4 * sin(TAU * 0.9 * u - 2.0 * ph + 2.0));
  col = mix(col, band, body * uOn);

  // Resting state: light glass with a faint frosted floor.
  vec3 rest = mix(ink, vec3(0.93, 0.92, 0.91), smoothstep(0.35, 1.0, y) * 0.5);
  col = mix(rest, col, uOn);

  // Glass thickness: light gathers along the inside of the rim, brightest
  // at the bottom where the frost scatters it.
  float low = smoothstep(0.4, 0.95, y);
  vec3 rimTint = mix(vec3(0.93, 0.92, 0.91), vec3(1.0), low);
  float inner = exp(-din / mix(0.035, 0.065, low)) * mix(0.42, 0.75, low);
  col = mix(col, rimTint, clamp(inner, 0.0, 1.0));
  float line = exp(-max(-sd, 0.0) / (1.0 * uPx));
  // A thin stone ring (stone-300) at the edge.
  col = mix(col, mix(vec3(0.84, 0.83, 0.82), vec3(0.95), low), line * 0.8);

  col += (hash(fc) - 0.5) * (2.5 / 255.0);
  col = clamp(col, 0.0, 1.0);
  float a = clamp(0.5 - sd, 0.0, 1.0);
  gl_FragColor = vec4(col * a, a);
}
`

function compile(gl: WebGLRenderingContext, type: number, src: string) {
  const s = gl.createShader(type)!
  gl.shaderSource(s, src)
  gl.compileShader(s)
  // A lost context fails every compile with no log; the restore handler rebuilds instead.
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) {
    console.error(gl.getShaderInfoLog(s))
  }
  return s
}

// Canvases whose context this component released on unmount, with the extension that can ask for it
// back (a lost context no longer hands the extension out).
const released = new WeakMap<HTMLCanvasElement, WEBGL_lose_context>()

// Resolve any CSS colour (hex, rgb, oklch, color-mix…) to RGB in 0..1.
function readColor(css: string, ctx: CanvasRenderingContext2D | null): [number, number, number] {
  const hex = css.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].replace(/./g, "$&$&") : hex[1]
    return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255]
  }
  if (!ctx) return [0.5, 0.5, 0.5]
  ctx.clearRect(0, 0, 1, 1)
  ctx.fillStyle = "#000"
  ctx.fillStyle = css
  ctx.fillRect(0, 0, 1, 1)
  const d = ctx.getImageData(0, 0, 1, 1).data
  return [d[0] / 255, d[1] / 255, d[2] / 255]
}

// Any number of colours → STOPS evenly spaced stops, flattened for uniform3fv.
function resample(colors: string[]) {
  let ctx: CanvasRenderingContext2D | null = null
  if (colors.some((c) => !/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c.trim()))) {
    const cv = document.createElement("canvas")
    cv.width = cv.height = 1
    ctx = cv.getContext("2d", { willReadFrequently: true })
  }
  const src = (colors.length ? colors : DEFAULT_COLORS).map((c) => readColor(c, ctx))
  if (src.length === 1) src.push(src[0])
  const out = new Float32Array(STOPS * 3)
  for (let i = 0; i < STOPS; i++) {
    const x = (i / (STOPS - 1)) * (src.length - 1)
    const a = Math.floor(x)
    const b = Math.min(a + 1, src.length - 1)
    const f = x - a
    for (let k = 0; k < 3; k++) out[i * 3 + k] = src[a][k] * (1 - f) + src[b][k] * f
  }
  return out
}

/** A frosted-glass pill with a band of colour flowing through it, shown while an answer is being worked out. */
export function ThinkingPill({
  label = "Thinking",
  dots = true,
  width = 360,
  height,
  speed = 1,
  colors = DEFAULT_COLORS,
  active = true,
  shimmer = true,
  className,
  style,
  ...props
}: ThinkingPillProps) {
  const h = height ?? Math.round(width * 0.3)
  const canvasRef = React.useRef<HTMLCanvasElement>(null)
  const textRef = React.useRef<HTMLSpanElement>(null)
  const labelRef = React.useRef<HTMLSpanElement>(null)
  const dotRefs = React.useRef<(HTMLSpanElement | null)[]>([])
  const activeRef = React.useRef(active)
  const kickRef = React.useRef<() => void>(() => {})
  const releaseRef = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // The one switch between the WebGL canvas and the CSS fallback. Only the effect below sets it.
  const [fallback, setFallback] = React.useState(false)
  const colorKey = colors.join("|")

  React.useEffect(() => {
    activeRef.current = active
    kickRef.current()
  }, [active])

  React.useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    // A run that follows a cleanup on this canvas (new props, or StrictMode's second run) takes the
    // context over, so the release queued by that cleanup is called off.
    clearTimeout(releaseRef.current)
    const gl = canvas.getContext("webgl", {
      premultipliedAlpha: true,
      alpha: true,
      antialias: false,
    })
    if (!gl) {
      setFallback(true)
      return
    }
    const lose = gl.getExtension("WEBGL_lose_context")
    const colorData = resample(colors)

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const pw = Math.round(width * dpr)
    const phh = Math.round(h * dpr)

    let raf = 0
    let visible = true
    let on = activeRef.current ? 1 : 0
    let last = performance.now()
    const start = last

    let prog: WebGLProgram | null = null
    let vs: WebGLShader | null = null
    let fs: WebGLShader | null = null
    let buf: WebGLBuffer | null = null
    let uRes: WebGLUniformLocation | null = null
    let uPx: WebGLUniformLocation | null = null
    let uPh: WebGLUniformLocation | null = null
    let uOn: WebGLUniformLocation | null = null

    // Everything the frame loop draws with. Runs on mount and again after a restored context.
    function build() {
      prog = gl!.createProgram()
      vs = compile(gl!, gl!.VERTEX_SHADER, VERT)
      fs = compile(gl!, gl!.FRAGMENT_SHADER, FRAG)
      if (!prog) return false
      gl!.attachShader(prog, vs)
      gl!.attachShader(prog, fs)
      gl!.linkProgram(prog)
      if (!gl!.getProgramParameter(prog, gl!.LINK_STATUS)) return false
      gl!.useProgram(prog)

      buf = gl!.createBuffer()
      gl!.bindBuffer(gl!.ARRAY_BUFFER, buf)
      gl!.bufferData(gl!.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl!.STATIC_DRAW)
      const loc = gl!.getAttribLocation(prog, "aPos")
      gl!.enableVertexAttribArray(loc)
      gl!.vertexAttribPointer(loc, 2, gl!.FLOAT, false, 0, 0)

      uRes = gl!.getUniformLocation(prog, "uRes")
      uPx = gl!.getUniformLocation(prog, "uPx")
      uPh = gl!.getUniformLocation(prog, "uPh")
      uOn = gl!.getUniformLocation(prog, "uOn")
      gl!.uniform3fv(gl!.getUniformLocation(prog, "uCol"), colorData)

      canvas!.width = pw
      canvas!.height = phh
      gl!.viewport(0, 0, pw, phh)
      gl!.clearColor(0, 0, 0, 0)
      return true
    }

    // Free this run's GPU objects but keep the context itself, which the next run on this canvas reuses.
    function destroy() {
      cancelAnimationFrame(raf)
      raf = 0
      if (!gl!.isContextLost()) {
        gl!.deleteProgram(prog)
        gl!.deleteShader(vs)
        gl!.deleteShader(fs)
        gl!.deleteBuffer(buf)
      }
      prog = vs = fs = buf = null
    }

    function begin() {
      if (build()) {
        setFallback(false)
        if (!raf) raf = requestAnimationFrame(frame)
      } else {
        destroy()
        setFallback(true)
      }
    }

    // The loop writes these inline; put them back to their resting look before the fallback shows.
    function resetText() {
      dotRefs.current.forEach((el) => {
        if (!el) return
        el.style.opacity = ""
        el.style.transform = ""
      })
      if (labelRef.current) labelRef.current.style.backgroundPosition = "100% 0"
    }

    function onLost(e: Event) {
      // Asking the browser to restore the context; the objects went with it.
      e.preventDefault()
      cancelAnimationFrame(raf)
      raf = 0
      prog = vs = fs = buf = null
      resetText()
      setFallback(true)
    }
    function onRestored() {
      begin()
    }
    canvas.addEventListener("webglcontextlost", onLost)
    canvas.addEventListener("webglcontextrestored", onRestored)

    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting
      if (visible && !raf && prog) raf = requestAnimationFrame(frame)
    })
    io.observe(canvas)

    function frame(now: number) {
      raf = 0
      if (!prog) return
      const t = reduce ? 0 : ((now - start) / 1000) * Math.max(speed, 0)
      const ph = (TAU * (((t % LOOP) + LOOP) % LOOP)) / LOOP
      // Ease the aurora toward its target over roughly half a second.
      const target = activeRef.current ? 1 : 0
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      on = reduce ? target : on + (target - on) * (1 - Math.exp(-dt * 6))
      if (Math.abs(target - on) < 0.002) on = target

      gl!.clear(gl!.COLOR_BUFFER_BIT)
      gl!.uniform2f(uRes, pw, phh)
      gl!.uniform1f(uPx, dpr)
      gl!.uniform1f(uPh, ph)
      gl!.uniform1f(uOn, on)
      gl!.drawArrays(gl!.TRIANGLES, 0, 3)

      // Label and dots ride the same clock, so a recording loops cleanly.
      const live = !reduce && activeRef.current
      dotRefs.current.forEach((el, i) => {
        if (!el) return
        // Eight waves per loop; each dot lifts and brightens a beat after the last.
        const w = live ? 0.5 + 0.5 * Math.cos(ph * 8 + 0.95 - i * 0.95) : 1
        el.style.opacity = String(0.4 + 0.6 * w)
        el.style.transform = live ? `translateY(${(-0.035 * w * w).toFixed(4)}em)` : ""
      })
      if (labelRef.current) {
        // A glint crosses the label twice per loop and rests off the word in between.
        const g = live ? ((ph / TAU) * 2) % 1 : 0
        labelRef.current.style.backgroundPosition = `${(100 - Math.min(g * 1.6, 1) * 100).toFixed(2)}% 0`
      }
      if (textRef.current) textRef.current.style.opacity = String(0.6 + 0.4 * on)

      // Keep drawing while it moves; at rest (reduced motion or inactive) stop once the fade lands.
      if (visible && (live || on !== target)) raf = requestAnimationFrame(frame)
    }
    kickRef.current = () => {
      if (!raf && prog) {
        last = performance.now()
        raf = requestAnimationFrame(frame)
      }
    }

    if (gl.isContextLost()) {
      // Lost before this run began: show the fallback until the restore event rebuilds it.
      setFallback(true)
      const ext = released.get(canvas)
      if (ext) {
        released.delete(canvas)
        ext.restoreContext()
      }
    } else {
      begin()
    }

    return () => {
      destroy()
      kickRef.current = () => {}
      io.disconnect()
      canvas.removeEventListener("webglcontextlost", onLost)
      canvas.removeEventListener("webglcontextrestored", onRestored)
      // Release the GPU context only once the canvas has really left the page. A re-run on this
      // canvas clears this timer first, and a canvas still on the page keeps its context.
      releaseRef.current = setTimeout(() => {
        if (canvas.isConnected || gl.isContextLost() || !lose) return
        released.set(canvas, lose)
        // Cancelling the loss keeps the context restorable if this canvas is ever shown again.
        canvas.addEventListener("webglcontextlost", (e) => e.preventDefault(), { once: true })
        lose.loseContext()
      }, 0)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, h, speed, colorKey])

  // Coming back from the fallback, React clears the inline label opacity it set; one frame puts it back.
  React.useEffect(() => {
    if (!fallback) kickRef.current()
  }, [fallback])

  const radius = h / 2
  const sweep = colors.length ? colors : DEFAULT_COLORS
  return (
    <div
      role="status"
      aria-live="polite"
      className={className}
      style={{
        width,
        height: h,
        position: "relative",
        borderRadius: radius,
        boxShadow: "0 0 0 1px rgba(214,211,209,0.9), 0 6px 18px -8px rgba(15,23,42,0.25)",
        ...style,
      }}
      {...props}
    >
      {fallback && (
        <div
          className="thinking-pill-fallback"
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: radius,
            overflow: "hidden",
            // Resting light glass, as the WebGL path draws it when inactive. The band covers it when active.
            backgroundImage: "linear-gradient(180deg, #fafaf9 0%, #fafaf9 35%, #f5f5f4 67%, #eeedeb 100%)",
          }}
        >
          {/* Three tiles of the colour sweep, each one pill wide, slid by one tile per loop. */}
          <div
            style={{
              position: "absolute",
              top: "-20%",
              bottom: "-20%",
              left: "-100%",
              width: "300%",
              backgroundImage: `linear-gradient(90deg, ${sweep.join(", ")}, ${sweep[0]})`,
              backgroundSize: "33.3333% 100%",
              filter: `blur(${Math.round(h * 0.08)}px)`,
              animation: `thinking-pill-flow ${LOOP / Math.max(speed, 0.01)}s linear infinite`,
              opacity: active ? 1 : 0,
              transition: "opacity 0.6s ease",
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              backgroundImage: "linear-gradient(180deg, #fafaf9 0%, #fafaf9 30%, rgba(250,250,249,0.6) 42%, rgba(250,250,249,0) 52%)",
            }}
          />
          {/* The milky frosted floor belongs to the aurora, so it fades out with it. */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              backgroundImage:
                "linear-gradient(180deg, rgba(250,250,249,0) 50%, rgba(250,250,249,0.7) 78%, rgba(255,255,255,0.9) 100%)",
              opacity: active ? 1 : 0,
              transition: "opacity 0.6s ease",
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: radius,
              boxShadow: `inset 0 0 0 1px rgba(255,255,255,0.6), inset 0 ${-h * 0.06}px ${h * 0.1}px rgba(255,255,255,0.5)`,
            }}
          />
          <style>{`@keyframes thinking-pill-flow{to{transform:translateX(33.3333%)}}@media (prefers-reduced-motion:reduce){.thinking-pill-fallback *{animation:none!important}}`}</style>
        </div>
      )}
      {/* Always mounted, so a context that comes back can take over from the fallback again. */}
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          display: "block",
          visibility: fallback ? "hidden" : undefined,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          whiteSpace: "nowrap",
          fontFamily: "inherit",
          fontSize: h * FONT,
          fontWeight: 600,
          letterSpacing: "0.008em",
          lineHeight: 1,
          // Dark slate on the light glass, with a soft white halo where the band runs behind it.
          color: "#1e293b",
          textShadow: "0 0 0.3em rgba(255,255,255,0.9), 0 0 0.12em rgba(255,255,255,0.9)",
          pointerEvents: "none",
          userSelect: "none",
        }}
      >
        <span
          ref={textRef}
          style={{
            display: "flex",
            alignItems: "baseline",
            // The WebGL loop drives this; the CSS fallback dims it here instead.
            ...(fallback ? { opacity: active ? 1 : 0.6, transition: "opacity 0.6s ease" } : null),
          }}
        >
          <span style={{ position: "relative" }}>
            {label}
            {shimmer && (
              <span
                ref={labelRef}
                aria-hidden="true"
                style={{
                  position: "absolute",
                  left: 0,
                  top: "-0.2em",
                  padding: "0.2em 0",
                  color: "transparent",
                  textShadow: "none",
                  // A band of light, a third as wide as the gradient, so it can rest off the word between passes.
                  backgroundImage: "linear-gradient(100deg, transparent 0 41%, rgba(255,255,255,0.95) 50%, transparent 59% 100%)",
                  backgroundSize: "300% 100%",
                  backgroundPosition: "100% 0",
                  WebkitBackgroundClip: "text",
                  backgroundClip: "text",
                  // Blurred, the clipped band turns into a glow that hugs the letters it passes.
                  filter: "blur(0.06em)",
                }}
              >
                {label}
              </span>
            )}
          </span>
          {dots && (
            <span aria-hidden="true" style={{ display: "flex" }}>
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  ref={(el) => {
                    dotRefs.current[i] = el
                  }}
                  style={{ display: "inline-block", marginLeft: i ? "0.02em" : "0" }}
                >
                  .
                </span>
              ))}
            </span>
          )}
        </span>
      </div>
    </div>
  )
}

export default ThinkingPill
