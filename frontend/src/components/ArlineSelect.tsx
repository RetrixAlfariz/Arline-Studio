import { useEffect, useId, useMemo, useRef, useState, type ComponentType } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

export interface ArlineSelectOption {
  value: string;
  label: string;
  description?: string;
  icon?: ComponentType<{ size?: number; strokeWidth?: number; "aria-hidden"?: boolean }>;
  disabled?: boolean;
}

interface ArlineSelectProps {
  value: string;
  options: ArlineSelectOption[];
  onValueChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  className?: string;
  density?: "default" | "compact" | "mode";
  disabled?: boolean;
  menuMinWidth?: number;
}

export function simpleOptions(values: Array<[string, string, string?]>): ArlineSelectOption[] {
  return values.map(([value, label, description]) => ({ value, label, description }));
}

export function ArlineSelect({
  value,
  options,
  onValueChange,
  ariaLabel,
  placeholder = "Choose an option",
  className = "",
  density = "default",
  disabled = false,
  menuMinWidth = 280,
}: ArlineSelectProps) {
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const [position, setPosition] = useState({ top: 0, left: 0, width: menuMinWidth, maxHeight: 320 });
  const selected = options.find((option) => option.value === value);
  const SelectedIcon = selected?.icon;

  const enabledIndexes = useMemo(
    () => options.map((option, index) => (!option.disabled ? index : -1)).filter((index) => index >= 0),
    [options],
  );

  useEffect(() => {
    if (!open) return;
    setActiveIndex(options.findIndex((option) => option.value === value) >= 0 ? options.findIndex((option) => option.value === value) : enabledIndexes[0] || 0);

    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const viewportPadding = 10;
      const width = Math.min(Math.max(rect.width, menuMinWidth), window.innerWidth - viewportPadding * 2);
      const estimatedHeight = Math.min(360, 18 + options.length * (density === "compact" ? 42 : 58));
      const spaceBelow = window.innerHeight - rect.bottom - viewportPadding;
      const openAbove = spaceBelow < Math.min(estimatedHeight, 240) && rect.top > spaceBelow;
      const maxHeight = Math.max(140, Math.min(360, openAbove ? rect.top - viewportPadding * 2 : spaceBelow));
      const rawLeft = Math.min(rect.left, window.innerWidth - width - viewportPadding);
      setPosition({
        top: openAbove ? Math.max(viewportPadding, rect.top - Math.min(estimatedHeight, maxHeight) - 6) : rect.bottom + 6,
        left: Math.max(viewportPadding, rawLeft),
        width,
        maxHeight,
      });
    };

    const closeFromOutside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };

    updatePosition();
    document.addEventListener("pointerdown", closeFromOutside);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [density, enabledIndexes, menuMinWidth, open, options, value]);

  const move = (direction: 1 | -1) => {
    if (!enabledIndexes.length) return;
    const current = enabledIndexes.indexOf(activeIndex);
    setActiveIndex(enabledIndexes[(current + direction + enabledIndexes.length) % enabledIndexes.length]);
  };

  const commit = (index: number) => {
    const option = options[index];
    if (!option || option.disabled) return;
    onValueChange(option.value);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) setOpen(true);
      else move(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Home" && open) {
      event.preventDefault();
      setActiveIndex(enabledIndexes[0] || 0);
    } else if (event.key === "End" && open) {
      event.preventDefault();
      setActiveIndex(enabledIndexes.at(-1) || 0);
    } else if ((event.key === "Enter" || event.key === " ") && open) {
      event.preventDefault();
      commit(activeIndex);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div className={`arline-select arline-select-${density} ${open ? "open" : ""} ${className}`.trim()}>
      <button
        ref={triggerRef}
        type="button"
        className="arline-select-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-menu`}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={onKeyDown}
      >
        {SelectedIcon ? <span className="arline-select-trigger-icon"><SelectedIcon size={density === "mode" ? 17 : 14} strokeWidth={1.8} aria-hidden /></span> : null}
        <span className="arline-select-trigger-copy">
          <strong>{selected?.label || placeholder}</strong>
          {density === "mode" && selected?.description ? <small>{selected.description}</small> : null}
        </span>
        <ChevronDown className="arline-select-chevron" size={14} strokeWidth={1.8} aria-hidden />
      </button>

      {open && createPortal(
        <div
          ref={menuRef}
          id={`${id}-menu`}
          className={`arline-select-menu arline-select-menu-${density}`}
          role="listbox"
          aria-label={ariaLabel}
          aria-activedescendant={`${id}-option-${activeIndex}`}
          style={{ position: "fixed", top: position.top, left: position.left, width: position.width, maxHeight: position.maxHeight }}
        >
          <div className="arline-select-options">
            {options.map((option, index) => {
              const Icon = option.icon;
              const isSelected = option.value === value;
              const isActive = index === activeIndex;
              return (
                <button
                  id={`${id}-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  disabled={option.disabled}
                  className={`${isSelected ? "selected" : ""} ${isActive ? "active" : ""}`.trim()}
                  key={option.value}
                  onPointerMove={() => !option.disabled && setActiveIndex(index)}
                  onClick={() => commit(index)}
                >
                  {Icon ? <span className="arline-select-option-icon"><Icon size={17} strokeWidth={1.7} aria-hidden /></span> : null}
                  <span className="arline-select-option-copy"><strong>{option.label}</strong>{option.description ? <small>{option.description}</small> : null}</span>
                  {isSelected ? <Check className="arline-select-check" size={15} strokeWidth={2.2} aria-hidden /> : null}
                </button>
              );
            })}
          </div>
        </div>,
        document.querySelector(".studio-shell") || document.body,
      )}
    </div>
  );
}
