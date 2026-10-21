# PixelForge AI Studio

A native Python desktop studio for social-media posts, advertisements and promotional graphics.

**Current stage: Stage 2 — AI generation with Google Gemini** (on top of the Stage 1 editor).
AI generation uses your own Google AI Studio API key, stored only in the git-ignored `.env` file. Without a key the editor still works fully and nothing is sent anywhere. Generated images are never faked.

## Run

```powershell
cd E:\2026\Python\PixelForgeAI
.\.venv\Scripts\activate
python main.py
```

Without activating the virtual environment:

```powershell
E:\2026\Python\PixelForgeAI\.venv\Scripts\python.exe main.py
```

**Desktop shortcut (Windows):** create a Desktop icon and a Start Menu entry that open the app without a console window:

```powershell
.\.venv\Scripts\python.exe tools\create_shortcut.py
```

Run it again if you move the project folder.

Install the dependencies (already present in `.venv`):

```powershell
python -m pip install -r requirements.txt
```

## Tests

```powershell
python -m unittest discover -s tests -v
```

The tests use temporary files and need no API key. The export tests render text with Qt in headless (`offscreen`) mode.

## Stage 1 features

| Area | What works |
| --- | --- |
| Layout | Three columns: navigation sidebar, design canvas, and right panel with **Generate / Adjust / Text** tabs. Dark studio theme, toasts, tooltips, empty state. |
| Open | PNG, JPEG and WebP via the button, Ctrl+O, or drag and drop. Files are validated, EXIF orientation is applied, and source files are never overwritten. |
| Canvas | QGraphicsView canvas. Zoom in/out, zoom presets, fit to screen, 100 % view, Ctrl+scroll to zoom, middle-drag to pan. |
| Transform | Crop (drag on the canvas or enter exact values), resize (aspect lock, crop-to-fill / pad / stretch), rotate left/right, flip H/V. |
| Colour | Brightness, contrast and saturation sliders with live preview, grayscale, reset adjustments. |
| Restore | **Reset All Image Edits** restores the original import. Adjustments are always re-applied to the base image, so they never accumulate quality loss. |
| Text | Add, edit, move (drag), select and delete text layers. Font, size, colour, bold, italic and alignment. Text stays editable until export. |
| History | Undo/redo for transforms, adjustments and text edits (Ctrl+Z, Ctrl+Y). |
| Export | PNG (keeps transparency) or JPEG (quality setting, transparent areas composited onto a chosen colour). Output size can be the canvas, any social preset or custom, with fill / fit / stretch. Exports only the design, never the app window. |
| Presets | Square 1080×1080, Portrait 1080×1350, Story 1080×1920, Landscape 1920×1080, Custom. Use them for new canvases, resizing and export. |
| Sample | **Load Sample Design** opens placeholder artwork drawn locally with Pillow. It has editable text layers and is not AI output. |
| AI panel | Prompt, example prompts, reference image upload/preview/replace/remove, design type, style and aspect ratio. **Generate** explains that the provider arrives in Stage 2. |

| Brand details | Optional company name, description, phone numbers and emails, each with a font size and colour, plus a colour theme. **Editable text layers** mode asks the AI for a design without text and adds your details as editable layers. **Draw text inside the AI image** mode sends the exact text, sizes and colours in the prompt. Details are remembered between sessions. |
| Select Area (M) | Rectangle, ellipse or freehand lasso selection. Inside the selection you can Adjust (with live preview), Blur, Sharpen, Remove (fills from the surroundings), Fill with a colour, Erase to transparent, or Crop. All actions can be undone. |
| Layers (Photoshop-style) | **Magic Wand** (click to select an area of similar colour, Shift+click adds, adjustable tolerance). **Copy Layer** (Ctrl+J) and **Cut Layer** (Shift+Ctrl+J) turn the selection into a movable image layer; Cut fills the hole. Drag a layer to move it and drag a corner handle to resize it. The **Layers** tab lists every layer with thumbnails and has opacity, size, rotation, flip, duplicate, up/down, merge into background and delete. **Add Image…** places a logo or photo as a layer. Layers are exported between the background and the text. |
| Input safety | Dropdowns, number boxes and sliders change only on click or typing; the mouse wheel scrolls the panel instead. |
| Advanced adjust | Filters (Vivid, Warm, Cool, Vintage, Dramatic, Fade, Mono, Noir, Sepia), highlights/shadows, warmth/tint/hue, sharpness, blur, vignette, sepia, invert, and rotate by any angle. |
| Advanced text | Heading/subheading/body presets, underline, UPPERCASE, letter spacing, line height, opacity, rotation, drop shadow, outline, background highlight, duplicate, layer order and centring. Canvas and export use the same renderer. |
| Theme | **Settings → Appearance**: choose **Dark**, **Light** or **System** (follows Windows light/dark, and switches live when Windows changes). The choice is saved with QSettings and restored at the next launch. Default: Dark. |

Placeholder pages with a planned stage: My Projects, Recent Designs, Templates (Stage 3) and Generation History (Stage 2). Settings also shows the AI provider section planned for Stage 2.

### Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| Open image / New canvas / Export | Ctrl+O / Ctrl+N / Ctrl+E |
| Undo / Redo | Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) |
| Zoom in / out / fit / 100 % | Ctrl+= / Ctrl+- / Ctrl+0 / Ctrl+1 |
| Crop mode, then apply / cancel | C, then Enter / Esc |
| Resize / Rotate left / Rotate right | Ctrl+R / Ctrl+[ / Ctrl+] |
| Add text / Delete selected text | Ctrl+T / Delete (canvas focused) |

## Project structure

```
main.py                     entry point
app_info.py                 name / version constants
models/
  design.py                 Adjustments, TextElement, DesignState (pure data)
  presets.py                social-media size presets
services/                   no widget code
  image_processor.py        Pillow operations: load/validate, crop, resize, rotate, flip, adjustments
  design_document.py        DesignDocument: original image, current state, undo/redo
  text_renderer.py          shared Qt text layout so canvas and export match
  export_service.py         compose image + text, fit to output size, save PNG/JPEG
  qt_image.py               Pillow <-> QImage conversion
  generation_service.py     AI provider interface (Stage 1: not configured)
  sample_artwork.py         locally drawn placeholder artwork
ui/
  main_window.py            window layout and editing controller
  editor_canvas.py          QGraphicsView canvas, text items, crop overlay
  generation_panel.py       AI prompt and reference-image panel
  adjust_panel.py           transform tools, sliders, presets
  text_panel.py             text layer properties
  dialogs.py                new design, resize, crop, export dialogs
  pages.py                  empty state, placeholder pages, About
  styles.py                 dark/light colour tokens, stylesheet, theme switching
  preferences.py            saved user preferences (theme)
  sidebar.py, widgets.py, icons.py
tests/                      unittest suites for processing, document, export, generation stub
storage/projects, storage/generated   reserved for Stage 2/3
```

### Design notes

- Scene coordinates equal image pixels. Text positions and sizes are stored in image pixels, so on-screen and exported layouts match.
- `DesignDocument` keeps the untouched original. Every edit produces a new Pillow image, so undo snapshots can share images cheaply. History holds the last 50 steps.
- Colour adjustments are previewed on a downscaled copy while a slider is dragged, then rendered at full size on a background thread.
- Crop shifts text layers and resize scales them. Rotate and flip change only the background image; text keeps its position, clamped to the canvas.

## Stage 2: AI generation

Choose the provider in **Settings → AI provider** (stored as `AI_PROVIDER` in `.env`):

| Provider | Key | Notes |
| --- | --- | --- |
| **Pollinations.ai** (`pollinations`) | none | Free and anonymous, good for testing. Only the prompt text and image size are sent, to a public third-party service (private mode requested), so avoid confidential details in prompts. Limits: one image every 45 seconds, about 0.6 MP output (enlarged to the preset size), a small "pollinations.ai" watermark, and no reference images. |
| **Manus AI** (`manus`) | Manus API key (`MANUS_API_KEY`) | Autonomous agent via Manus API v2. Each image is one Manus task (`task.create`, then polling `task.listMessages`, then downloading the image attachment). Takes about 1–5 minutes and uses Manus credits. Agent profile `MANUS_AGENT_PROFILE`: `lite` (default), `standard` or `max`. Supports reference images. Test Connection shows your credit balance without creating a task. |
| **Google Gemini** (`gemini`) | Google AI Studio key | Higher quality and supports reference images. Needs billing enabled; the free tier's image quota is 0. |

### Google Gemini

### Setup
1. Get a key at <https://aistudio.google.com/apikey>.
2. Add the key in either of these ways:
   - In the app: **Settings → AI provider**, paste the key, choose a model, then click **Save**.
   - In a file: copy `.env.example` to `.env` and set `GEMINI_API_KEY=...`.
3. Click **Test Connection**. This checks the key with Google and uses no image quota.

> **Quota:** Google's free tier currently allows **0 image-generation requests** (`limit: 0`). A key without billing passes Test Connection, but Generate shows *"Image quota unavailable"*. To generate images, enable billing on the key's project in Google AI Studio.

### How it works
- `services/gemini_provider.py` calls `POST /v1beta/models/{model}:generateContent` using the standard library only. The key is sent in the `x-goog-api-key` header, never in the URL.
- The request contains the prompt, design type, art style, aspect ratio (1:1, 4:5, 9:16 or 16:9) and an optional reference image. Reference images are downscaled to 1536 px or less before upload.
- Generation runs on a background thread, so you can keep editing while it works.
- The result is cropped to the selected social preset (for example 1080×1350) and opened on the canvas, ready for text and export.
- Each result is saved to `storage/generated/` as a PNG plus a `.json` file with the prompt and settings.
- API errors become plain-language messages: invalid key, missing model, free tier without image quota, rate limit with retry time, safety block, network failure.
- Models you can choose in Settings: `gemini-3.1-flash-image` (default), `gemini-3.1-flash-lite-image`, `gemini-2.5-flash-image`, `gemini-3-pro-image`.

### Configuration (`.env`)
| Key | Meaning |
| --- | --- |
| `GEMINI_API_KEY` | Your Google AI Studio key (required for AI generation). |
| `GEMINI_IMAGE_MODEL` | Model id (optional, default `gemini-3.1-flash-image`). |

Environment variables with the same names override `.env`.
