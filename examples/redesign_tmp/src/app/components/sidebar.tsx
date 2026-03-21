import { 
  LayoutDashboard, 
  ShoppingBag, 
  Users, 
  BarChart3, 
  Settings, 
  FileText,
  Package,
  Headphones,
  Zap
} from "lucide-react";
import { Button } from "./ui/button";

const navigation = [
  { name: "Dashboard", icon: LayoutDashboard, active: true },
  { name: "Orders", icon: ShoppingBag, active: false },
  { name: "Products", icon: Package, active: false },
  { name: "Customers", icon: Users, active: false },
  { name: "Analytics", icon: BarChart3, active: false },
  { name: "Reports", icon: FileText, active: false },
];

const bottomNav = [
  { name: "Support", icon: Headphones },
  { name: "Settings", icon: Settings },
];

export function Sidebar() {
  return (
    <aside className="w-64 border-r border-gray-800 bg-[#0a0a0f] flex flex-col">
      <div className="p-6 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <div className="size-8 bg-gradient-to-br from-emerald-500 to-cyan-500 rounded-lg flex items-center justify-center">
            <Zap className="size-5 text-black" />
          </div>
          <span className="text-lg font-semibold text-emerald-400 font-mono">SPARKER</span>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {navigation.map((item) => {
          const Icon = item.icon;
          return (
            <Button
              key={item.name}
              variant="ghost"
              className={`w-full justify-start gap-3 font-mono ${
                item.active 
                  ? "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 hover:text-emerald-400 border border-emerald-500/20" 
                  : "text-gray-400 hover:bg-gray-900 hover:text-gray-200"
              }`}
            >
              <Icon className="size-5" />
              {item.name}
            </Button>
          );
        })}
      </nav>

      <div className="p-3 space-y-1 border-t border-gray-800">
        {bottomNav.map((item) => {
          const Icon = item.icon;
          return (
            <Button
              key={item.name}
              variant="ghost"
              className="w-full justify-start gap-3 text-gray-400 hover:bg-gray-900 hover:text-gray-200 font-mono"
            >
              <Icon className="size-5" />
              {item.name}
            </Button>
          );
        })}
      </div>
    </aside>
  );
}