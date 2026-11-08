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

/** Notion-style neutrals: warm grays that do not take on the accent hue. */
export function appearancePalette(_accent: string, theme: ThemeMode) {
  if (theme === "light") {
    const text = "#37352F";
    return {
      surface: "#F7F7F5", surface0: "#F7F6F3", surface1: "#F7F7F5", surface2: "#FFFFFF",
      surface3: "#EFEFED", surface4: "#E3E2E0", canvas: "#FFFFFF",
      text, textSoft: "#4A4843", muted: "#787774", soft: "#9B9A97",
      line: alpha(text, .09), lineStrong: alpha(text, .16), hover: alpha(text, .06),
    };
  }
  const text = "#D4D4D4";
  return {
    surface: "#202020", surface0: "#252525", surface1: "#202020", surface2: "#252525",
    surface3: "#2F2F2F", surface4: "#373737", canvas: "#191919",
    text, textSoft: "#C4C4C4", muted: "#9B9B9B", soft: "#7D7D7D",
    line: "rgba(255,255,255,0.094)", lineStrong: "rgba(255,255,255,0.16)", hover: "rgba(255,255,255,0.055)",
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
    // Selection and active states stay neutral (gray hover fill); the accent is
    // reserved for primary actions, links, focus rings and status.
    "--core-soft": settings.contrast === "high" ? palette.lineStrong : palette.hover,
    "--core-line": settings.contrast === "high" ? alpha(accent, .68) : palette.lineStrong,
    "--core-glow": alpha(accent, settings.contrast === "high" ? .45 : .32),
    "--core-shadow": "transparent",
    "--hover": palette.hover,
    "--accent-foreground": readableForeground(accent),
  } as CSSProperties;
}
