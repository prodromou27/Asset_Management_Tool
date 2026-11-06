import {
  BatteryCharging, Boxes, Computer, HardDrive, Laptop, Layers, Monitor, Mouse,
  Network, Package, Phone, PlugZap, Printer, Router, ScanLine, Server, ShieldCheck,
  Tv, Wifi, type LucideIcon,
} from 'lucide-react'
import type { AssetCategory } from '../api/types'

const ICONS: Record<string, LucideIcon> = {
  workstations: Computer,
  servers: Server,
  networking: Network,
  security: ShieldCheck,
  printers: Printer,
  monitors: Monitor,
  'ip-phones': Phone,
  tvs: Tv,
  ups: BatteryCharging,
  power: PlugZap,
  storage: HardDrive,
  peripherals: Mouse,
  other: Package,
  'workstations-laptop': Laptop,
  'servers-virtual-machine': Layers,
  'networking-router': Router,
  'networking-access-point': Wifi,
  'printers-scanner': ScanLine,
}

export function CategoryIcon({ category, categories = [], size = 18, className }: {
  category?: AssetCategory | null
  categories?: AssetCategory[]
  size?: number
  className?: string
}) {
  let current = category
  const visited = new Set<string>()
  let Icon: LucideIcon = Boxes
  // Custom child categories inherit their parent's symbol; custom roots stay generic.
  while (current && !visited.has(current.id)) {
    visited.add(current.id)
    if (Object.hasOwn(ICONS, current.code)) {
      Icon = ICONS[current.code]
      break
    }
    current = categories.find((item) => item.id === current?.parent)
  }
  return <Icon size={size} strokeWidth={1.75} className={className} aria-hidden="true" focusable="false" />
}
