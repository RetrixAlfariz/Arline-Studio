import type { CSSProperties } from "react";
import type { AppearanceSettings, ThemeMode } from "./types";

export const DEFAULT_ACCENT = "#2F9B81";
export const DEFAULT_APPEARANCE: AppearanceSettings = { mode: "system", accent: DEFAULT_ACCENT, contrast: "standard" };

type Rgb = { r: number; g: number; b: number };
type Hsl = { h: number; s: number; l: number };

export function normalizeHex(value: string): string {
  const raw = value.trim();
  const short = /^#([0-9a-f]{3})$/i.exec(raw);
  if (short) return `#${short[1].split("").map((part) => part + part).join("")}`.toUpperCase();
  return /^#[0-9a-f]{6}$/i.test(raw) ? raw.toUpperCase() : DEFAULT_ACCENT;
}

function hexToRgb(value: string): Rgb {
  const hex = normalizeHex(value).slice(1);
  return { r: parseInt(hex.slice(0, 2), 16), g: parseInt(hex.slice(2, 4), 16), b: parseInt(hex.slice(4, 6), 16) };
}

function rgbToHex({ r, g, b }: Rgb): string {
  const byte = (value: number) => Math.round(Math.max(0, Math.min(255, value))).toString(16).padStart(2, "0");
  return `#${byte(r)}${byte(g)}${byte(b)}`.toUpperCase();
}

function rgbToHsl({ r, g, b }: Rgb): Hsl {
  const [red, green, blue] = [r, g, b].map((value) => value / 255);
  const max = Math.max(red, green, blue); const min = Math.min(red, green, blue);
  const delta = max - min; let h = 0;
  if (delta) {
    if (max === red) h = ((green - blue) / delta) % 6;
    else if (max === green) h = (blue - red) / delta + 2;
    else h = (red - green) / delta + 4;
    h = (h * 60 + 360) % 360;
  }
  const l = (max + min) / 2;
  const s = delta ? delta / (1 - Math.abs(2 * l - 1)) : 0;
  return { h, s: s * 100, l: l * 100 };
}

function hslToRgb({ h, s, l }: Hsl): Rgb {
  const saturation = s / 100; const lightness = l / 100;
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const x = chroma * (1 - Math.abs((h / 60) % 2 - 1)); const m = lightness - chroma / 2;
  let channels: [number, number, number] = [0, 0, 0];
  if (h < 60) channels = [chroma, x, 0]; else if (h < 120) channels = [x, chroma, 0];
  else if (h < 180) channels = [0, chroma, x]; else if (h < 240) channels = [0, x, chroma];
  else if (h < 300) channels = [x, 0, chroma]; else channels = [chroma, 0, x];
  return { r: (channels[0] + m) * 255, g: (channels[1] + m) * 255, b: (channels[2] + m) * 255 };
}

function alpha(value: string, opacity: number): string {
  const { r, g, b } = hexToRgb(value);
  return `rgba(${r},${g},${b},${opacity})`;
}

export function resolveAccent(value: string, theme: ThemeMode): string {
  const hsl = rgbToHsl(hexToRgb(value));
  return rgbToHex(hslToRgb({ h: hsl.h, s: Math.max(38, Math.min(78, hsl.s)), l: theme === "dark" ? Math.max(58, Math.min(68, hsl.l)) : Math.max(34, Math.min(46, hsl.l)) }));
}

function luminance(value: string): number {
  const rgb = hexToRgb(value);
  const channel = (part: number) => { const linear = part / 255; return linear <= .04045 ? linear / 12.92 : ((linear + .055) / 1.055) ** 2.4; };
  return .2126 * channel(rgb.r) + .7152 * channel(rgb.g) + .0722 * channel(rgb.b);
}

export function contrastRatio(first: string, second: string): number {
  const [bright, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (bright + .05) / (dark + .05);
}

export function readableForeground(background: string): "#FFFFFF" | "#1E2120" {
  return contrastRatio(background, "#FFFFFF") >= contrastRatio(background, "#1E2120") ? "#FFFFFF" : "#1E2120";
}

export function appearancePalette(value: string, theme: ThemeMode) {
  const hue = rgbToHsl(hexToRgb(value)).h;
  const tone = (s: number, l: number) => rgbToHex(hslToRgb({ h: hue, s, l }));
  if (theme === "light") {
    const text = tone(11, 17);
    return {
      surface: tone(11, 94), surface0: tone(10, 91), surface1: tone(9, 98), surface2: "#FFFFFF",
      surface3: tone(11, 91), surface4: tone(12, 85), canvas: tone(9, 96),
      text, textSoft: tone(10, 29), muted: tone(8, 43), soft: tone(7, 58),
      line: alpha(text, .11), lineStrong: alpha(text, .20),
    };
  }
  const text = tone(8, 95);
  return {
    surface: tone(10, 10), surface0: tone(10, 7), surface1: tone(10, 9), surface2: tone(11, 12),
    surface3: tone(12, 16), surface4: tone(12, 21), canvas: tone(9, 8),
    text, textSoft: tone(8, 86), muted: tone(8, 65), soft: tone(8, 48),
    line: alpha(text, .10), lineStrong: alpha(text, .19),
  };
}

export function appearanceVariables(settings: AppearanceSettings, theme: ThemeMode): CSSProperties {
  const accent = resolveAccent(settings.accent, theme);
  const brightHsl = rgbToHsl(hexToRgb(accent));
  const bright = rgbToHex(hslToRgb({ ...brightHsl, l: theme === "dark" ? Math.min(76, brightHsl.l + 8) : Math.max(27, brightHsl.l - 7) }));
  const palette = appearancePalette(settings.accent, theme);
  return {
    "--surface": palette.surface,
    "--surface-0": palette.surface0,
    "--surface-1": palette.surface1,
    "--surface-2": palette.surface2,
    "--surface-3": palette.surface3,
    "--surface-4": palette.surface4,
    "--canvas": palette.canvas,
    "--line": settings.contrast === "high" ? alpha(palette.text, .20) : palette.line,
    "--line-strong": settings.contrast === "high" ? alpha(palette.text, .34) : palette.lineStrong,
    "--text": palette.text,
    "--text-soft": palette.textSoft,
    "--muted": palette.muted,
    "--soft": palette.soft,
    "--core": accent,
    "--core-bright": bright,
    "--core-soft": alpha(accent, settings.contrast === "high" ? .20 : .12),
    "--core-line": alpha(accent, settings.contrast === "high" ? .68 : .44),
    "--core-glow": alpha(bright, settings.contrast === "high" ? .32 : .20),
    "--core-shadow": alpha(accent, settings.contrast === "high" ? .30 : .18),
    "--accent-foreground": readableForeground(accent),
  } as CSSProperties;
}
