# Sidebar Shadow Design QA

- Source visual truth: `C:\Users\Revian\AppData\Local\Temp\codex-clipboard-ad01958c-744f-44ea-a1bb-ed3be5cabfe7.png` (245 x 77 px) and `C:\Users\Revian\AppData\Local\Temp\codex-clipboard-e45fa008-07f9-4138-8fd6-387f12e967bb.png` (280 x 71 px)
- Implementation screenshot: `E:\Developen\Github\Arline Studio\design-qa-sidebar-shadow-final.png` (248 x 330 px)
- Focused comparison: `E:\Developen\Github\Arline Studio\design-qa-shadow-comparison.png` (540 x 220 px)
- Browser viewport: 1280 x 720 CSS px, device pixel ratio 1
- State: dark theme, custom pink accent, New chat control and active Chat navigation control
- Density normalization: all captures use 1x pixels; focused controls are displayed without resampling in the comparison board

## Full-view comparison evidence

The sidebar capture confirms the new elevation remains contained within each control and does not muddy adjacent separators, branding, or navigation groups. The previous long accent glow is gone.

## Focused comparison evidence

The comparison board places the supplied Codex controls next to the corresponding Arline controls. Both now use a short contact shadow, a faint ambient falloff, and a subtle inset highlight. Arline intentionally retains its configured accent color and existing 5 px component radius.

## Required fidelity surfaces

- Fonts and typography: unchanged; text remains crisp and keeps the existing Arline hierarchy. No wrapping or truncation regression is visible.
- Spacing and layout rhythm: control dimensions and sidebar spacing are unchanged. Shadows do not alter layout or overlap dividers.
- Colors and tokens: shadow opacity is close to the subdued Codex reference. Accent shadow now derives from `--core`, so custom accent colors remain coherent.
- Image quality and assets: no image assets were introduced or replaced; existing Lucide icons and Arline brand asset remain sharp.
- Copy and content: unchanged.
- Interaction and accessibility: hover/focus states retain visible boundaries; transitions are limited to 160 ms and no layout movement was added.

## Comparison history

### Initial pass

- P2: the new ambient shadow used a hard-coded green value while the active user accent was pink.
- Fix: replaced static RGB values with `color-mix(in srgb, var(--core), transparent)` in dark, light, and hover shadow layers.

### Final pass

- Computed styles show the ambient layer resolving from the active pink `--core` value.
- Browser console errors: none.
- No actionable P0, P1, or P2 differences remain. The accent hue and existing radius differ from Codex intentionally to preserve Arline's design system.

## Follow-up polish

- P3: consider adding an explicit selected state for the active recent-chat row; this is outside the requested shadow adjustment.

final result: passed
