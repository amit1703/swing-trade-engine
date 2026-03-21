import { Bell, Search, Settings, User, Terminal } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "./ui/avatar";

export function DashboardHeader() {
  return (
    <header className="border-b border-gray-800 bg-[#0a0a0f] px-6 py-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-8">
          <h1 className="text-2xl font-semibold text-emerald-400">Dashboard</h1>
          <div className="flex items-center gap-2">
            <Terminal className="size-4 text-gray-500" />
            <span className="text-sm text-gray-500 font-mono">v2.4.1</span>
          </div>
        </div>

        <div className="flex flex-1 max-w-md items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-gray-500" />
            <Input
              type="search"
              placeholder="Search..."
              className="pl-9 bg-gray-900 border-gray-800 text-gray-200 placeholder:text-gray-600"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="relative text-gray-400 hover:text-gray-200 hover:bg-gray-900">
            <Bell className="size-5" />
            <span className="absolute top-1.5 right-1.5 size-2 bg-red-500 rounded-full animate-pulse" />
          </Button>
          
          <Button variant="ghost" size="icon" className="text-gray-400 hover:text-gray-200 hover:bg-gray-900">
            <Settings className="size-5" />
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="gap-2 text-gray-400 hover:text-gray-200 hover:bg-gray-900">
                <Avatar className="size-8 border border-emerald-500">
                  <AvatarImage src="https://images.unsplash.com/photo-1758630737900-a28682c5aa69?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxidXNpbmVzcyUyMHByb2Zlc3Npb25hbCUyMHdvcmtzcGFjZXxlbnwxfHx8fDE3NzM5MzMwMjZ8MA&ixlib=rb-4.1.0&q=80&w=1080" />
                  <AvatarFallback className="bg-gray-800 text-emerald-400">JD</AvatarFallback>
                </Avatar>
                <span className="hidden sm:inline">John Doe</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="bg-gray-900 border-gray-800">
              <DropdownMenuLabel className="text-gray-200">My Account</DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-gray-800" />
              <DropdownMenuItem className="text-gray-300 focus:bg-gray-800 focus:text-gray-200">Profile</DropdownMenuItem>
              <DropdownMenuItem className="text-gray-300 focus:bg-gray-800 focus:text-gray-200">Settings</DropdownMenuItem>
              <DropdownMenuItem className="text-gray-300 focus:bg-gray-800 focus:text-gray-200">Billing</DropdownMenuItem>
              <DropdownMenuSeparator className="bg-gray-800" />
              <DropdownMenuItem className="text-red-400 focus:bg-gray-800 focus:text-red-400">Log out</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}