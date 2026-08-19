import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react'

// What leaves the browser: the square that was framed, at the size the server
// stores. Its own centred crop then has nothing left to do. JPEG rather than
// webp, because the server re-encodes whatever arrives and not every engine's
// toBlob can write a webp at all.
const EXPORT_SIDE = 512
const EXPORT_TYPE = 'image/jpeg'
const EXPORT_QUALITY = 0.9

// How far in a picture may be pushed, as a multiple of the scale that just
// fills the frame. Past this a phone photograph is drawing single pixels.
const MAX_ZOOM = 8

// The slider's hundred steps are a power of the zoom range rather than a share
// of it, so a step near the bottom moves as much of the picture as one near the
// top.
const ZOOM_STEPS = 100

// A notch of wheel, in pixels, for the browsers that measure one in lines.
const LINE_HEIGHT = 16

// Where the picture sits under the frame: laid out at its natural size, scaled
// by scale, its top left corner at (tx, ty) in the frame's own pixels.
interface Frame {
  scale: number
  tx: number
  ty: number
}

// As far out as a picture can be pulled: the shorter of its sides exactly
// filling the frame. Any further out and the frame would hold something that is
// not photograph.
function minScale(photo: ImageBitmap, view: number): number {
  return view / Math.min(photo.width, photo.height)
}

// Every move and every zoom ends here rather than being checked when the button
// is pressed, so there is no moment at which the frame holds anything but
// picture: the corner is kept between the frame's own edge and where the far
// edge of the photograph would land.
function clamp(frame: Frame, photo: ImageBitmap, view: number): Frame {
  const out = minScale(photo, view)
  const scale = Math.min(Math.max(frame.scale, out), out * MAX_ZOOM)
  return {
    scale,
    tx: Math.min(0, Math.max(view - photo.width * scale, frame.tx)),
    ty: Math.min(0, Math.max(view - photo.height * scale, frame.ty)),
  }
}

// Zoom about one point, so whatever is under the fingers or the cursor stays
// under them while the rest of the picture grows around it.
function zoomAt(
  frame: Frame,
  photo: ImageBitmap,
  view: number,
  x: number,
  y: number,
  factor: number,
): Frame {
  const out = minScale(photo, view)
  const scale = Math.min(Math.max(frame.scale * factor, out), out * MAX_ZOOM)
  const grew = scale / frame.scale
  return clamp(
    { scale, tx: x - (x - frame.tx) * grew, ty: y - (y - frame.ty) * grew },
    photo,
    view,
  )
}

// Where a picture starts: as far out as it goes, and centred, which is the
// whole of the shorter side and the middle of the longer one.
function fitted(photo: ImageBitmap, view: number): Frame {
  const scale = minScale(photo, view)
  return {
    scale,
    tx: (view - photo.width * scale) / 2,
    ty: (view - photo.height * scale) / 2,
  }
}

// The picture, turned the way it was taken. A phone writes the sensor's pixels
// and a tag saying which way is up; asking for the orientation here is what
// reads that tag, and reading it is the whole of why a portrait photograph no
// longer arrives lying on its side. The file is decoded as it stands, with no
// address made for it, which the policy this app is served under would not
// allow an image to be loaded from anyway.
async function upright(file: File): Promise<ImageBitmap> {
  try {
    return await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    // Engines old enough to refuse the option outright rather than ignore it.
    return await createImageBitmap(file)
  }
}

interface Props {
  file: File
  // The upload belongs to the screen that opened this, so what it is doing is
  // told rather than found out.
  busy: boolean
  error: string
  onUse: (framed: Blob) => void
  onCancel: () => void
}

// Framing a profile picture before it is sent. The square on screen is the
// square that leaves: nothing is shown here that will not be shown everywhere,
// and nothing is cut off afterwards that was inside the frame.
//
// It is drawn on a canvas rather than moved about with a transform because the
// app is served with no inline styles allowed, and a live transform is a style
// written on an element hundreds of times a second. The maths is the same
// either way: the frame is a window onto the picture at (-tx/scale, -ty/scale),
// as wide and as tall as view/scale, and that one rectangle is what the preview
// draws and what the export draws.
export default function AvatarCrop({ file, busy, error, onUse, onCancel }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const view = useRef<HTMLCanvasElement>(null)
  // Live pointers by id; two of them is a pinch. Kept aside from the render
  // because a gesture reads the newest positions, not the newest drawing.
  const pointers = useRef(new Map<number, { x: number; y: number }>())

  const [photo, setPhoto] = useState<ImageBitmap | null>(null)
  // The frame's side in CSS pixels, measured rather than written down: it is a
  // share of the panel, and the panel is a share of whatever screen this is.
  const [side, setSide] = useState(0)
  const [frame, setFrame] = useState<Frame | null>(null)
  const [readError, setReadError] = useState('')

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  useEffect(() => {
    let live = true
    let made: ImageBitmap | null = null
    upright(file)
      .then((bitmap) => {
        made = bitmap
        if (live) setPhoto(bitmap)
        else bitmap.close()
      })
      .catch(() => {
        if (live) setReadError('That picture could not be read. Try another.')
      })
    return () => {
      live = false
      made?.close()
    }
  }, [file])

  // The frame is however wide the panel lets it be, which changes with the
  // window and with a phone turning over.
  useEffect(() => {
    const canvas = view.current
    if (!canvas) return
    const watch = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (box) setSide(box.width)
    })
    watch.observe(canvas)
    return () => watch.disconnect()
  }, [])

  // A picture arriving starts centred; a frame that changed size keeps what was
  // framed and pulls it back inside the new edges.
  useEffect(() => {
    if (!photo || side <= 0) return
    setFrame((held) => (held === null ? fitted(photo, side) : clamp(held, photo, side)))
  }, [photo, side])

  useEffect(() => {
    const canvas = view.current
    if (!canvas || !photo || !frame || side <= 0) return
    const ink = canvas.getContext('2d')
    if (!ink) return
    // The canvas holds the frame's size in real device pixels, so the preview is
    // as sharp as the screen is. Capped, because three times over is already
    // past what anybody can see.
    const dots = Math.round(side * Math.min(window.devicePixelRatio || 1, 3))
    if (canvas.width !== dots) {
      canvas.width = dots
      canvas.height = dots
    }
    ink.clearRect(0, 0, dots, dots)
    ink.drawImage(
      photo,
      -frame.tx / frame.scale,
      -frame.ty / frame.scale,
      side / frame.scale,
      side / frame.scale,
      0,
      0,
      dots,
      dots,
    )
  }, [photo, frame, side])

  // Listened for here rather than through a prop because the page behind must
  // not scroll while a picture is being zoomed, and only a listener that says
  // it is not passive is allowed to say so.
  useEffect(() => {
    const canvas = view.current
    if (!canvas || !photo || side <= 0) return
    const turn = (event: WheelEvent) => {
      event.preventDefault()
      const box = canvas.getBoundingClientRect()
      const rolled = event.deltaMode === 1 ? event.deltaY * LINE_HEIGHT : event.deltaY
      setFrame(
        (held) =>
          held &&
          zoomAt(
            held,
            photo,
            side,
            event.clientX - box.left,
            event.clientY - box.top,
            Math.exp(-rolled / 300),
          ),
      )
    }
    canvas.addEventListener('wheel', turn, { passive: false })
    return () => canvas.removeEventListener('wheel', turn)
  }, [photo, side])

  function grab(event: ReactPointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId)
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
  }

  function move(event: ReactPointerEvent<HTMLCanvasElement>) {
    const was = pointers.current.get(event.pointerId)
    if (!was || !photo || side <= 0) return
    const now = { x: event.clientX, y: event.clientY }
    const held = pointers.current
    const other = [...held].find(([id]) => id !== event.pointerId)?.[1]

    if (other) {
      // A pinch: the other finger is the anchor, the gap between the two is the
      // zoom, and the point between them is what it is zoomed about.
      const before = Math.hypot(was.x - other.x, was.y - other.y)
      const after = Math.hypot(now.x - other.x, now.y - other.y)
      const box = event.currentTarget.getBoundingClientRect()
      if (before > 0) {
        setFrame(
          (one) =>
            one &&
            zoomAt(
              one,
              photo,
              side,
              (now.x + other.x) / 2 - box.left,
              (now.y + other.y) / 2 - box.top,
              after / before,
            ),
        )
      }
    } else {
      setFrame(
        (one) =>
          one &&
          clamp(
            { ...one, tx: one.tx + now.x - was.x, ty: one.ty + now.y - was.y },
            photo,
            side,
          ),
      )
    }
    held.set(event.pointerId, now)
  }

  function release(event: ReactPointerEvent<HTMLCanvasElement>) {
    pointers.current.delete(event.pointerId)
  }

  // The slider zooms about the middle of the frame, which is the only point it
  // can mean: there is no finger on the picture to keep in place.
  function slide(step: number) {
    if (!photo || side <= 0) return
    const wanted = minScale(photo, side) * Math.pow(MAX_ZOOM, step / ZOOM_STEPS)
    setFrame(
      (one) => one && zoomAt(one, photo, side, side / 2, side / 2, wanted / one.scale),
    )
  }

  // The one rectangle the preview is showing, drawn again at the size the
  // server keeps. Nothing is worked out here that was not already on screen.
  function send() {
    if (!photo || !frame || side <= 0) return
    const out = document.createElement('canvas')
    out.width = EXPORT_SIDE
    out.height = EXPORT_SIDE
    const ink = out.getContext('2d')
    if (!ink) {
      setReadError('That picture could not be prepared. Try another.')
      return
    }
    ink.drawImage(
      photo,
      -frame.tx / frame.scale,
      -frame.ty / frame.scale,
      side / frame.scale,
      side / frame.scale,
      0,
      0,
      EXPORT_SIDE,
      EXPORT_SIDE,
    )
    out.toBlob(
      (blob) => {
        if (blob) onUse(blob)
        else setReadError('That picture could not be prepared. Try another.')
      },
      EXPORT_TYPE,
      EXPORT_QUALITY,
    )
  }

  const zoom =
    photo === null || frame === null || side <= 0
      ? 0
      : Math.max(
          0,
          Math.round(
            (Math.log(frame.scale / minScale(photo, side)) / Math.log(MAX_ZOOM)) *
              ZOOM_STEPS,
          ),
        )
  const shownError = readError || error

  return (
    <dialog
      className="overlay overlay-middle"
      ref={dialog}
      aria-labelledby="crop-title"
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onCancel()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id="crop-title">Frame your picture</h2>
          <p className="hint">
            Drag to move, pinch or scroll to zoom. The square is what everyone sees.
          </p>
        </header>

        <div className="crop-body">
          <canvas
            className="crop-view"
            ref={view}
            aria-label="Your picture as it will be shown"
            onPointerDown={grab}
            onPointerMove={move}
            onPointerUp={release}
            onPointerCancel={release}
          />

          <label className="crop-zoom">
            <span className="label">Zoom</span>
            <input
              type="range"
              min={0}
              max={ZOOM_STEPS}
              step={1}
              value={zoom}
              disabled={frame === null || busy}
              onChange={(event) => slide(Number(event.target.value))}
            />
          </label>

          {shownError && (
            <p className="error" role="alert">
              {shownError}
            </p>
          )}
          {busy && (
            <p className="hint" role="status">
              Uploading.
            </p>
          )}

          <button
            type="button"
            className="secondary"
            disabled={busy || frame === null}
            onClick={send}
          >
            Use this picture
          </button>
        </div>

        <footer className="overlay-foot">
          <button type="button" className="secondary" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        </footer>
      </section>
    </dialog>
  )
}
