"""A bounded RGB sketch surface and transactional PNG documents."""
from pathlib import Path
from PIL import Image, ImageDraw, UnidentifiedImageError
from storage import atomic_write, validate_path

WIDTH, HEIGHT, HISTORY = 464, 194, 16
PALETTE = ('#202936', '#ffffff', '#ef6b73', '#f2bc57', '#66cf98', '#6aa7e9', '#b58ce6', '#a76f4b')
SIZES = (1, 3, 6, 10)


class Drawing:
    def __init__(self):
        self.image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
        self.undo_stack, self.redo_stack = [], []
        self.color, self.size, self.eraser = 0, 1, False
        self.last, self.dirty, self.path = None, False, None
        self.warning = ''

    @staticmethod
    def point(x, y):
        return max(0, min(WIDTH-1, int(x))), max(0, min(HEIGHT-1, int(y)))

    def checkpoint(self):
        self.undo_stack.append(self.image.copy())
        del self.undo_stack[:-HISTORY]
        self.redo_stack.clear()

    def begin(self, x, y):
        self.checkpoint()
        self.last = self.point(x,y)
        self.stroke(x,y)

    def stroke(self, x, y):
        point = self.point(x,y)
        if self.last is None:
            return
        draw = ImageDraw.Draw(self.image)
        color = '#ffffff' if self.eraser else PALETTE[self.color]
        size = SIZES[self.size]
        draw.line((self.last, point), fill=color, width=size)
        radius = (size-1)/2
        draw.ellipse((point[0]-radius, point[1]-radius, point[0]+radius, point[1]+radius), fill=color)
        self.last, self.dirty = point, True

    def end(self):
        self.last = None

    def undo(self, redo=False):
        self.end()
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source:
            return False
        target.append(self.image)
        del target[:-HISTORY]
        self.image = source.pop()
        self.dirty = True
        return True

    def clear(self):
        self.end()
        self.checkpoint()
        self.image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
        self.dirty = True

    def new(self):
        self.end()
        self.image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.path, self.dirty = None, False

    def open(self, path):
        path = validate_path(path)
        if not path.is_file() or path.stat().st_size > 8*1024*1024:
            raise ValueError('Image is missing or exceeds 8 MiB')
        try:
            with Image.open(path) as image:
                if image.format not in ('PNG', 'JPEG') or image.width*image.height > 4_000_000:
                    raise ValueError('Use a PNG/JPEG image below 4 megapixels')
                image.load()
                image = image.convert('RGBA')
                image.thumbnail((WIDTH, HEIGHT))
                replacement = Image.new('RGB', (WIDTH, HEIGHT), 'white')
                replacement.paste(image, ((WIDTH-image.width)//2, (HEIGHT-image.height)//2), image)
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise ValueError('Image is malformed or unsupported') from error
        self.end()
        self.image = replacement
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.path = path if path.suffix.lower() == '.png' else None
        self.dirty = False

    def save(self, path=None):
        target = self.path if path is None else Path(path)
        if target is None or target.suffix.lower() != '.png':
            raise ValueError('Choose a PNG filename')
        self.warning = atomic_write(target, lambda stream: self.image.save(stream, format='PNG'))
        self.path, self.dirty = target, False
        return target
