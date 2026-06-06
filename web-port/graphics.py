# graphics.py - browser/Canvas shim for the subset of John Zelle's graphics.py
# used by blockbreaker.py. Runs under Pyodide and renders to an HTML5
# <canvas id="game">. It is NOT a full reimplementation of Zelle's library -
# only the classes and methods the game actually touches are provided.
import asyncio
from js import document, window
from pyodide.ffi import create_proxy

# Tk/X11 colour name -> CSS hex, for names CSS doesn't know (red4, ...) or
# renders differently (X11 "green" is bright, CSS "green" is dark).
_COLORS = {
    "red": "#ff0000", "orange": "#ffa500", "yellow": "#ffff00",
    "green": "#00ff00", "blue": "#0000ff", "white": "#ffffff",
    "black": "#000000",
    "red4": "#8b0000", "orange4": "#8b5a00", "blue4": "#00008b",
    "yellow4": "#8b8b00", "green4": "#008b00",
}


def _css(color):
    if color is None or color == "":
        return None
    return _COLORS.get(str(color).lower(), str(color))


def color_rgb(r, g, b):
    return "#%02x%02x%02x" % (r, g, b)


# The single active window, painted by the JS requestAnimationFrame loop.
_active_win = None


def render_active():
    if _active_win is not None:
        _active_win._render()


class Point:
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)

    def getX(self):
        return self.x

    def getY(self):
        return self.y

    def clone(self):
        return Point(self.x, self.y)


class GraphicsObject:
    def __init__(self):
        self.fill = ""
        self.outline = "black"
        self.width = 1
        self.win = None
        self._drawn = False

    def setFill(self, color):
        self.fill = color

    def setOutline(self, color):
        self.outline = color

    def setWidth(self, w):
        self.width = w

    def draw(self, win):
        if not self._drawn:
            win._add(self)
            self.win = win
            self._drawn = True
        return self

    def undraw(self):
        if self._drawn and self.win is not None:
            self.win._remove(self)
            self._drawn = False

    def move(self, dx, dy):
        self._move(dx, dy)

    def _move(self, dx, dy):
        pass

    def _render(self, ctx, win):
        pass


class Rectangle(GraphicsObject):
    def __init__(self, p1, p2):
        super().__init__()
        self.p1 = p1.clone()
        self.p2 = p2.clone()

    def getP1(self):
        return self.p1.clone()

    def getP2(self):
        return self.p2.clone()

    def getCenter(self):
        return Point((self.p1.x + self.p2.x) / 2, (self.p1.y + self.p2.y) / 2)

    def _move(self, dx, dy):
        self.p1.x += dx
        self.p1.y += dy
        self.p2.x += dx
        self.p2.y += dy

    def _render(self, ctx, win):
        x1, y1 = win._sx(self.p1.x), win._sy(self.p1.y)
        x2, y2 = win._sx(self.p2.x), win._sy(self.p2.y)
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        if _css(self.fill):
            ctx.fillStyle = _css(self.fill)
            ctx.fillRect(x, y, w, h)
        if _css(self.outline):
            ctx.lineWidth = self.width
            ctx.strokeStyle = _css(self.outline)
            # Snap the stroke to the pixel grid (+0.5) so a 1px outline lands on
            # a single pixel line at full brightness, instead of straddling two
            # columns/rows and anti-aliasing to a dimmer line. Keeps a coloured
            # border as vivid as the block's fill.
            sx = round(x) + 0.5
            sy = round(y) + 0.5
            sw = round(x + w) - round(x) - 1
            sh = round(y + h) - round(y) - 1
            ctx.strokeRect(sx, sy, sw, sh)


class Circle(GraphicsObject):
    def __init__(self, center, radius):
        super().__init__()
        self.center = center.clone()
        self.radius = float(radius)

    def getCenter(self):
        return self.center.clone()

    def getRadius(self):
        return self.radius

    def _move(self, dx, dy):
        self.center.x += dx
        self.center.y += dy

    def _render(self, ctx, win):
        cx, cy = win._sx(self.center.x), win._sy(self.center.y)
        # Non-uniform setCoords means a "circle" is really an ellipse on screen,
        # which matches Zelle's behaviour under setCoords.
        rx, ry = self.radius * win.xscale, self.radius * win.yscale
        ctx.beginPath()
        ctx.ellipse(cx, cy, rx, ry, 0, 0, 6.283185307179586)
        if _css(self.fill):
            ctx.fillStyle = _css(self.fill)
            ctx.fill()
        if _css(self.outline):
            ctx.lineWidth = self.width
            ctx.strokeStyle = _css(self.outline)
            ctx.stroke()


class Line(GraphicsObject):
    def __init__(self, p1, p2):
        super().__init__()
        self.p1 = p1.clone()
        self.p2 = p2.clone()
        self.outline = "black"

    def _move(self, dx, dy):
        self.p1.x += dx
        self.p1.y += dy
        self.p2.x += dx
        self.p2.y += dy

    def _render(self, ctx, win):
        ctx.beginPath()
        ctx.moveTo(win._sx(self.p1.x), win._sy(self.p1.y))
        ctx.lineTo(win._sx(self.p2.x), win._sy(self.p2.y))
        ctx.lineWidth = self.width
        ctx.strokeStyle = _css(self.outline) or "#000000"
        ctx.stroke()


_FONT_FAMILIES = {
    "courier": "'Courier New', Courier, monospace",
    "helvetica": "Helvetica, Arial, sans-serif",
    "arial": "Arial, sans-serif",
    "times": "'Times New Roman', Times, serif",
}


class Text(GraphicsObject):
    def __init__(self, center, text):
        super().__init__()
        self.anchor = center.clone()
        self.text = str(text)
        self.size = 12
        self.face = "courier"
        self.color = "black"
        self.style = "normal"

    def setText(self, t):
        self.text = str(t)

    def getText(self):
        return self.text

    def setFill(self, c):
        self.color = c

    def setTextColor(self, c):
        self.color = c

    def setSize(self, s):
        self.size = s

    def setFace(self, f):
        self.face = f

    def setStyle(self, s):
        self.style = s

    def _move(self, dx, dy):
        self.anchor.x += dx
        self.anchor.y += dy

    def _render(self, ctx, win):
        family = _FONT_FAMILIES.get(str(self.face).lower(), "monospace")
        px = self.size * 1.3
        weight = "bold" if "bold" in str(self.style).lower() else "normal"
        italic = "italic " if "italic" in str(self.style).lower() else ""
        ctx.font = "%s%s %dpx %s" % (italic, weight, int(px), family)
        ctx.fillStyle = _css(self.color) or "#ffffff"
        ctx.textAlign = "center"
        ctx.textBaseline = "middle"
        cx, cy = win._sx(self.anchor.x), win._sy(self.anchor.y)
        lines = self.text.split("\n")
        lh = px * 1.25
        start = cy - (len(lines) - 1) * lh / 2.0
        for i, line in enumerate(lines):
            ctx.fillText(line, cx, start + i * lh)


class Entry(GraphicsObject):
    """Text entry, rendered as a real HTML <input> overlaid on the canvas."""

    def __init__(self, center, width):
        super().__init__()
        self.anchor = center.clone()
        self.cols = width
        self.fill = "white"
        self.color = "black"
        self.face = "courier"
        self.input = None

    def setFill(self, c):
        self.fill = c

    def setTextColor(self, c):
        self.color = c

    def setFace(self, f):
        self.face = f

    def setText(self, t):
        if self.input is not None:
            self.input.value = str(t)

    def getText(self):
        return self.input.value if self.input is not None else ""

    def draw(self, win):
        self.win = win
        self._drawn = True
        inp = document.createElement("input")
        inp.type = "text"
        inp.maxLength = self.cols
        rect = win.canvas.getBoundingClientRect()
        sx = rect.width / win.width
        sy = rect.height / win.height
        cx = win._sx(self.anchor.x) * sx
        cy = win._sy(self.anchor.y) * sy
        w = self.cols * 16
        inp.style.position = "absolute"
        inp.style.left = "%dpx" % int(cx - w / 2)
        inp.style.top = "%dpx" % int(cy - 16)
        inp.style.width = "%dpx" % w
        inp.style.height = "28px"
        inp.style.textAlign = "center"
        inp.style.font = "16px " + _FONT_FAMILIES.get(str(self.face).lower(), "monospace")
        inp.style.background = _css(self.fill) or "#ffffff"
        inp.style.color = _css(self.color) or "#000000"
        inp.style.border = "2px solid #888"
        inp.style.zIndex = "10"
        win.overlay.appendChild(inp)
        self.input = inp
        inp.focus()
        return self

    def undraw(self):
        if self.input is not None:
            self.input.remove()
            self.input = None
        self._drawn = False


class GraphWin:
    def __init__(self, title="", width=200, height=200, autoflush=True):
        global _active_win
        self.canvas = document.getElementById("game")
        self.canvas.width = width
        self.canvas.height = height
        self.width = width
        self.height = height
        self.ctx = self.canvas.getContext("2d")
        # Overlay container (same positioned parent as the canvas) for Entry inputs.
        self.overlay = document.getElementById("overlay")
        self.items = []
        self.background = "white"
        # Default to a pixel coordinate system until setCoords is called.
        self.xll, self.yll, self.xur, self.yur = 0, 0, width, height
        self._recalc()
        self._clicks = []
        self.closed = False
        self._click_proxy = create_proxy(self._on_click)
        self.canvas.addEventListener("click", self._click_proxy)
        # Held-pointer tracking (touch drag / mouse hold) for continuous bat
        # steering on touchscreens. Pointer Events unify touch, mouse and pen.
        self._pointer_down = False
        self._pointer_x = None
        self._pointer_proxies = [
            create_proxy(self._on_pointer_down),
            create_proxy(self._on_pointer_move),
            create_proxy(self._on_pointer_up),
        ]
        self.canvas.addEventListener("pointerdown", self._pointer_proxies[0])
        self.canvas.addEventListener("pointermove", self._pointer_proxies[1])
        # Listen for up/cancel on document so releasing off-canvas still clears.
        document.addEventListener("pointerup", self._pointer_proxies[2])
        document.addEventListener("pointercancel", self._pointer_proxies[2])
        try:
            document.title = title
        except Exception:
            pass
        _active_win = self

    def _recalc(self):
        self.xscale = self.width / float(self.xur - self.xll)
        self.yscale = self.height / float(self.yur - self.yll)

    def setCoords(self, xll, yll, xur, yur):
        self.xll, self.yll, self.xur, self.yur = xll, yll, xur, yur
        self._recalc()

    def setBackground(self, color):
        self.background = color

    # world -> screen pixels (y flipped so larger world-y is higher up)
    def _sx(self, x):
        return (x - self.xll) * self.xscale

    def _sy(self, y):
        return self.height - (y - self.yll) * self.yscale

    def _add(self, obj):
        self.items.append(obj)

    def _remove(self, obj):
        try:
            self.items.remove(obj)
        except ValueError:
            pass

    # Convert a DOM clientX to a world x-coordinate, accounting for CSS scaling.
    def _world_x(self, client_x):
        rect = self.canvas.getBoundingClientRect()
        sx = self.width / rect.width
        px = (client_x - rect.left) * sx
        return px / self.xscale + self.xll

    def _on_click(self, event):
        rect = self.canvas.getBoundingClientRect()
        sx = self.width / rect.width
        sy = self.height / rect.height
        px = (event.clientX - rect.left) * sx
        py = (event.clientY - rect.top) * sy
        lx = px / self.xscale + self.xll
        ly = (self.height - py) / self.yscale + self.yll
        self._clicks.append(Point(lx, ly))

    # --- Held-pointer tracking (touch drag / mouse hold) ------------------
    def _on_pointer_down(self, event):
        self._pointer_down = True
        self._pointer_x = self._world_x(event.clientX)

    def _on_pointer_move(self, event):
        if self._pointer_down:
            self._pointer_x = self._world_x(event.clientX)

    def _on_pointer_up(self, event):
        self._pointer_down = False

    # True while a finger/mouse is held down within the play area (x <= 100);
    # the stats/stop-button column (x > 100) is excluded so taps there don't
    # drag the bat. Used by the game to steer the bat toward pointerX().
    def pointerActive(self):
        return (self._pointer_down and self._pointer_x is not None
                and self._pointer_x <= 100)

    def pointerX(self):
        return self._pointer_x

    def checkMouse(self):
        if self._clicks:
            return self._clicks.pop(0)
        return None

    async def getMouse(self):
        while not self._clicks:
            await asyncio.sleep(0.01)
        return self._clicks.pop(0)

    def _render(self):
        ctx = self.ctx
        ctx.fillStyle = _css(self.background) or "#000000"
        ctx.fillRect(0, 0, self.width, self.height)
        for obj in list(self.items):
            obj._render(ctx, self)

    def close(self):
        self.closed = True
        ctx = self.ctx
        ctx.fillStyle = "#000000"
        ctx.fillRect(0, 0, self.width, self.height)
        self.items = []
        ctx.fillStyle = "#ffffff"
        ctx.font = "30px 'Courier New', monospace"
        ctx.textAlign = "center"
        ctx.textBaseline = "middle"
        ctx.fillText("Game Closed", self.width / 2, self.height / 2)


# Expose the render callback to the JS animation loop. Keep a reference to the
# proxy so it is not garbage collected.
_render_proxy = create_proxy(render_active)
window.__bbRender = _render_proxy
