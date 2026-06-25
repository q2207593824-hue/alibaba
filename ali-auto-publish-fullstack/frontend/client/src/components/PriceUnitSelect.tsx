import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/** 阿里发品页计量单位可选值 */
export const PRICE_UNIT_OPTIONS: readonly string[] = [
  "Bag/Bags",
  "Kilometer/Kilometers",
  "Ton/Tons",
  "Square Meter/Square Meters",
  "Cubic Meter/Cubic Meters",
  "Dozen/Dozens",
  "Gallon/Gallons",
  "Kilogram/Kilograms",
  "Gram/Grams",
  "Bushel/Bushels",
  "Barrel/Barrels",
  "Short Ton/Short Tons",
  "Set/Sets",
  "Pack/Packs",
  "Liter/Liters",
  "Yard/Yards",
  "Milligram/Milligrams",
  "Unit/Units",
  "Acre/Acres",
  "Ampere/Amperes",
  "Box/Boxes",
  "Carton/Cartons",
  "Pound/Pounds",
  "Case/Cases",
  "Centimeter/Centimeters",
  "Chain/Chains",
  "Cubic Centimeter/Cubic Centimeters",
  "Cubic Foot/Cubic Feet",
  "Cubic Inch/Cubic Inches",
  "Cubic Yard/Cubic Yards",
  "Degrees Celsius",
  "Degrees Fahrenheit",
  "Dram/Drams",
  "Piece/Pieces",
  "Fluid Ounce/Fluid Ounces",
  "Foot/Feet",
  "Furlong/Furlongs",
  "Gill/Gills",
  "Grain/Grains",
  "Hectare/Hectares",
  "Hertz",
  "Inch/Inches",
  "Kiloampere/Kiloamperes",
  "Kilohertz",
  "Pair/Pairs",
  "Kiloohm/Kiloohms",
  "Kilovolt/Kilovolts",
  "Kilowatt/Kilowatts",
  "Megahertz",
  "Mile/Miles",
  "Milliampere/Milliamperes",
  "Millihertz",
  "Milliliter/Milliliters",
  "Millimeter/Millimeters",
  "Milliohm/Milliohms",
  "Ounce/Ounces",
  "Millivolt/Millivolts",
  "Milliwatt/Milliwatts",
  "Nautical Mile/Nautical Miles",
  "Ohm/Ohms",
  "Parcel/Parcels",
  "Perch/Perches",
  "Pint/Pints",
  "Pole/Poles",
  "Quart/Quarts",
  "Quarter/Quarters",
  "Metric Ton/Metric Tons",
  "Rod/Rods",
  "Roll/Rolls",
  "Square Centimeter/Square Centimeters",
  "Square Foot/Square Feet",
  "Square Inch/Square Inches",
  "Square Mile/Square Miles",
  "Square Yard/Square Yards",
  "Stone/Stones",
  "Tonne/Tonnes",
  "Tray/Trays",
  "Meter/Meters",
  "Volt/Volts",
  "Watt/Watts",
  "Wp",
  "Twenty-Foot Container",
  "Strand/Strands",
  "Plant/Plants",
  "Pallet/Pallets",
  "Gross",
  "Forty-Foot Container",
  "Sheet/Sheets",
  "Long Ton/Long Tons",
  "Carat/Carats",
  "Blade/Blades",
  "Combo/Combos",
] as const;

const OPTION_SET = new Set<string>(PRICE_UNIT_OPTIONS);

export const DEFAULT_PRICE_UNIT = "Piece/Pieces";

export function isValidPriceUnit(value: string): boolean {
  return OPTION_SET.has(value.trim());
}

export function priceUnitCommandFilter(value: string, search: string): number {
  const q = search.trim().toLowerCase();
  if (!q) return 1;

  const lower = value.toLowerCase();
  if (lower === q) return 1;
  if (lower.startsWith(q)) return 0.96;

  const parts = lower.split("/");
  if (parts.some((p) => p === q)) return 0.94;
  if (parts.some((p) => p.startsWith(q))) return 0.9;
  if (lower.includes(q)) return 0.78;
  if (parts.some((p) => p.includes(q))) return 0.72;

  const tokens = q.split(/\s+/).filter(Boolean);
  if (tokens.length > 1 && tokens.every((t) => lower.includes(t))) return 0.55;

  return 0;
}

type PriceUnitSelectProps = {
  value: string;
  onChange: (value: string) => void;
  className?: string;
};

export function PriceUnitSelect({ value, onChange, className }: PriceUnitSelectProps) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "h-9 w-full justify-between font-normal text-sm",
            !value && "text-muted-foreground",
            className,
          )}
        >
          <span className="truncate">
            {value && isValidPriceUnit(value) ? value : value || "请选择计量单位"}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
        <Command filter={priceUnitCommandFilter}>
          <CommandInput placeholder="搜索计量单位..." />
          <CommandList>
            <CommandEmpty>无匹配项</CommandEmpty>
            <CommandGroup>
              {PRICE_UNIT_OPTIONS.map((unit) => (
                <CommandItem
                  key={unit}
                  value={unit}
                  onSelect={() => {
                    onChange(unit);
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === unit ? "opacity-100" : "opacity-0",
                    )}
                  />
                  {unit}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
